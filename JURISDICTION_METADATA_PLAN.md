# Jurisdiction & title extraction improvement plan

Written 2026-08-15, out of the `/meetings` audit that followed the
Granicus (204) + Swagit (207) bulk ingests. Companion findings live in
`BACKLOG.md`'s Bugs section (Granicus jurisdiction bleed, Swagit blank
jurisdiction) — this file is the *plan*, those entries are the *evidence*.
Deprioritized ideas from the same conversation are parked at the bottom of
`BACKLOG.md` under "Deprioritized ideas".

## The problem, in one paragraph

Every adapter extracts jurisdiction (and title) its own way — body-text
regex (Granicus), capitalization-bounded walk (PrimeGov), `<title>`-tail
parse (Swagit), URL slug (ClerkBase), h1/og:title assembly
(generic_fallback), API field (CivicClerk), hardcoded constant
(Seattle/SLC/Aurora/Viebit) — and only 10 of 20 adapters feed the shared
state-enrichment module (`app/utils/jurisdiction_enrich.py`). The
2026-08-15 audit of all 649 archived pages found ~16 bled jurisdictions
(regex ran past the real name into agenda text), ~22 blank ones (Swagit
special-purpose entities with no fallback), and a long tail of one-off
weirdness. The fix is not per-incident regex surgery; it's measurement,
then shared machinery.

## Workstreams (user-approved 2026-08-15)

### 1. Baseline validation — run first, no fetching needed

Run all 649 stored jurisdiction values through the existing Census tables
(`app/utils/jurisdiction_data/`). Classify each: exact-valid /
repairable-by-prefix-trim / legitimately-absent special entity / blank.
This quantifies the damage, tests the prefix-trim theory against real
data before production code, and produces the seed list for the
domain-pair table (workstream 4).

### 2. The tournament — cross-adapter extraction bake-off

Fetch raw HTML for all 649 source URLs (politely paced, same cadence as
the bulk ingests). Decompose the adapters' extraction heuristics into
portable signal extractors and run **every extractor against every page**:

- body-text `(City|County|Town) of` regex (Granicus-style)
- the same, with the combined **period-stop + capitalization-stop** rule
  (user's call: period-stop alone fixes Hercules/Huntsville/Milwaukee;
  capitalization-stop alone fixes Fort Worth; together they cover both
  families. "St."/"Ste."/"Ft."/"Mt." exceptions derived empirically from
  the Census places table, not hand-guessed)
- capitalization-bounded walk (PrimeGov-style, as shipped)
- `<title>`-tail `", ST"` parse (Swagit-style)
- URL-slug parse (ClerkBase-style)
- h1 / og:title / `<title>`-split assembly (generic_fallback-style)
- subdomain humanization (Granicus's wordninja fallback)

Score automatically: a name that validates against the Census tables
(exact or via prefix-trim) is presumed good; ties and not-in-table
outputs go to the human sheet. Deliverable: **one sheet, one row per
URL, one column per extractor**, for joint review — the user explicitly
wants to eyeball this together rather than trust the auto-score alone.

**Title is captured in the same pass but scored in a later round** — the
fetch is the expensive part and the HTML is the same; extractor columns
for title (page `<title>`, h1 assembly, og:title, slug) ride along in
the sheet now, and title-specific scoring/fixes become their own
follow-up once jurisdiction lands. (Title errors aren't bleed-shaped, so
the Census-validation scorer doesn't apply — different judge needed.)

Hypotheses to test, stated up front so the data can kill them:
- a few conventions (Granicus body regex, Swagit title-tail, ClerkBase
  slug, generic_fallback assembly) each do well *frequently* and belong
  in a shared fallback chain;
- generic_fallback's multi-tier assembly outperforms most bespoke
  single-regex extractors (user's hunch);
- longest-valid-prefix trimming repairs nearly every bleed case with no
  adapter regex changes (Claude's hunch).

### 3. Implement what the data says

Rough expected shape (subject to tournament results):

- **Enricher grows validation + canonicalization**: exact table match =
  high confidence; longest-valid-prefix trim repairs bleed (with a
  tail-sanity check so a real long agency name never gets truncated);
  not-in-table = keep unchanged but flag low-confidence. Never reject —
  school districts / MPOs / authorities are correct names no city table
  will ever contain.
- **ZIP-derived *name* suggestion** (today ZIP only fills in state): when
  an adapter has no name at all (blank Swagit cases), a ZIP-anchored
  address in page text can propose a city, carried with an explicit
  "Maybe:"-style confidence flag — county-seat false positives are
  accepted and flagged rather than avoided.
- **Optional `meeting_body` field** on `ResolvedMeeting`/`MeetingPage`:
  "Housing Authority of the County of Santa Clara" → jurisdiction "Santa
  Clara County, CA" + body "Housing Authority". Granicus's
  `_fetch_channel_info()` already parses a body value out of the RSS
  channel title, so there's precedent and one live data source; needs a
  schema addition (zero-friction via `create_all` for the new column? No
  — new *column* on existing table needs Alembic, see README's database
  section). Sequenced late; design before build.
- **Shared fallback chain**: promote the tournament's winning extractors
  into machinery every adapter can call after its own primary extraction
  comes up empty (Swagit and generic_fallback first — highest volume,
  currently never call the enricher at all).
- **Period+capitalization stop rule lands in the body-text regex
  regardless** (user's call): even with trim-repair in the enricher,
  entities that will never be in the Census table (water districts etc.)
  get no trim backstop, so the extractor itself should stop cleaner.
- **Domain-pair table growth**: every audit row whose jurisdiction
  validates cleanly seeds a verified `(domain, jurisdiction)` pair for
  `_KNOWN_DOMAINS` (or a successor data file if the dict outgrows
  hand-maintenance).

### 4. Verify + backfill

Re-run the 649 through the improved pipeline (dry-run comparison sheet,
same format), confirm improvement, then backfill damaged archived pages
via the existing `/admin/recheck-archive-page` endpoint.

## Sequencing decision

Tests before tweaks: workstream 1 today, tournament next, implementation
only where the tournament shows improvement, title round after
jurisdiction lands.

## Results so far

**Workstream 1 (baseline, ran 2026-08-15)**: 649 stored jurisdictions →
510 valid / 73 trim-reachable / 44 not-in-table / 22 blank. The
tail-sanity check splits the trim bucket cleanly: 16 true bleed (all
correct repairs) vs 57 legitimate long entities trimming would destroy —
so trim must always be gated on bleed signals. New bugs found by the
validation itself (wordninja acronym garbage incl. the sfwmd→", MD"
misread, galesburg over-split, dates-as-jurisdiction, places.csv missing
Census "(balance)" consolidated cities, Saint↔St. gap, townships absent,
one Canadian jurisdiction) are logged in `BACKLOG.md`'s Bugs section.

**Workstream 2 (tournament, ran 2026-08-15)**: all 649 source pages
fetched (0 failures), every extractor run against every page, scored by
table validation. Validity per extractor (valid/trim/none/blank of 649):

| extractor | valid | trim~ | none? | blank |
|---|---|---|---|---|
| stored (today) | 510 | 16 | 101 | 22 |
| granicus_body (shipped) | 318 | 68 | 50 | 213 |
| **prop_stoprule** (period+cap stop) | **361** | 2 | 73 | 213 |
| primegov_walk (shipped) | 326 | 2 | 87 | 234 |
| swagit_titletail | 179 | 0 | 45 | 425 |
| clerkbase_slug | 2 | 0 | 0 | 647 |
| fallback_titletag | 178 | 1 | 74 | 396 |
| subdomain_shipped (wordninja) | 408 | 0 | 229 | 12 |
| **prop_subdomain_validated** | **416** | 0 | **0** | 233 |

Both proposed extractors beat their shipped counterparts outright: the
stop rule converts 43 more pages to table-valid and eliminates bleed
(68→2 trim-needed); table-validated subdomain lookup gets more hits than
wordninja with *zero* garbage (declines instead of guessing — the whole
point). A fallback chain (stoprule → swagit_titletail →
fallback_titletag → subdomain_validated) reaches 528/649 table-valid vs
today's 510, and — the part that matters more than the topline — fixes
**all 51 pages whose stored jurisdiction is currently invalid-but-
chain-recoverable**, including every bleed case, both dates-as-
jurisdiction pages, Tucson (blank today), and Galesburg.

**Caution confirmed by the same data**: validation-failure ≠ wrong.
"Nashville-Davidson County, TN" → chain proposes "Davidson County"
(a *downgrade* — the real name is just missing from places.csv);
"Housing Authority of the County of Santa Clara" → "County of Santa
Clara" (loses the body — the `meeting_body` field candidate). So in
production the chain fills blanks and repairs *bleed-flagged* values
only; it never overwrites a non-validating stored name that lacks bleed
signals. Full sheet: `tournament_sheet.csv` (delivered 2026-08-15;
regenerate via the tournament script logged in this plan's workstream 2).

**Also empirically settled**: clerkbase_slug does not generalize (2 hits
outside its home platform) — drop it from the chain.
**Sequential-contribution correction** (computed after the table above):
fallback_titletag contributes **zero** unique coverage once the other
tiers run first (its 178 hits are all covered), and its non-validating
outputs are real junk (bare dates, "Auroratv") — dropped from the chain.
primegov_walk, contrary to the redundancy guess, adds 63 unique pages
after stoprule — kept. Final chain: **domain registry → adapter-native →
stoprule → primegov_walk → swagit_titletail → validated subdomain →
keep-and-flag**, reaching 536/649 before the registry tier even counts.

## Design refinements settled in review (2026-08-15)

- **Entity-prefix split, not discard**: "Housing Authority of the County
  of Santa Clara" → jurisdiction "County of Santa Clara, CA" + body
  "Housing Authority" (the `meeting_body` field). The rule is "never
  *lose information* without bleed signals" — trailing bleed gets
  repaired, leading entity prefixes over a table-valid jurisdiction get
  *split*, and everything else keeps its stored value.
- **Consolidated metros**: fix `scripts/build_jurisdiction_data.py` to
  keep Census "(balance)" entries (Nashville-Davidson, Louisville/
  Jefferson, Indianapolis, Baton Rouge — ~40 nationwide) instead of
  hand-listing them; keep a small alias map only for display-form
  variants (Saint↔St., okina/apostrophe, "Metro" phrasings).
- **Registry lives in the enricher, not per-adapter**: the known-domain
  lookup becomes the enricher's first step, with per-entry strength —
  *authoritative* (overrides even successful extraction; SLC's case,
  rare, evidence-backed only) vs *fallback* (used when extraction is
  blank or fails validation). Single-tenant domains only — a shared
  multi-tenant host (videoplayer.telvue.com, youtube.com) must never
  get an entry. The Holladay lesson motivates the authoritative tier:
  plausible-but-wrong extractions ("City of Holladay, UT") pass table
  validation, so validation alone can never fix a confirmed-misleading
  domain.
- **PrimeGov's own override stays untouched during the testing phase**
  (user's call 2026-08-15) — it's live, verified, and load-bearing for
  SLC in prod. Once the enricher-side registry is built and proven, it
  becomes redundant and can be deleted — logged in `BACKLOG.md` as a
  future refactor.
