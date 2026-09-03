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

## Implementation status (2026-08-15)

**Slice 1 (branch `jurisdiction-pipeline-r1`, commit `b3c8df4`)**: data-layer
fix (Census "(balance)" consolidated governments) + normalization fix
(the Greeley collision) + tests. Landed first, see BACKLOG_DONE.md.

**Slice 2 (same branch, uncommitted at time of writing)**: the enricher
upgrade, per the design above.
- `app/utils/jurisdiction_enrich.py` gained `finalize_jurisdiction()` --
  the single ingest-time entry point (`_table_lookup`, `_looks_like_bleed`,
  `_trim_repair`, `_split_entity_prefix`, `JurisdictionResult`). Validated
  against all 649 real audit rows before wiring anything in: 490
  validated, 111 unverified (correctly left alone), 31 blank, 17 repaired,
  9 authoritative (every SLC/Holladay case fixed). Two real bugs caught by
  that validation pass before shipping, not after: `_split_entity_prefix`
  was over-firing on "The City of Memphis"/"City and County of Denver"
  (fixed via `_is_bare_type_phrase`, which treats a leading article/"and"
  as transparent rather than only catching a single bare word); a test
  asserting fallback-domain entries only fire on blank input was itself
  wrong -- the shipped design (fallback fires on blank OR non-validating
  input, `authoritative` is the only tier that overrides a real-looking
  extraction) is correct for confirmed single-tenant hosts.
- `KnownJurisdiction` gained a `strength` field (`"fallback"` default,
  `"authoritative"` only for `slc.primegov.com` so far) -- data-only
  change, PrimeGov's own separate override code path is untouched per the
  "leave PrimeGov alone during testing" call (BACKLOG.md's deferred-
  refactor entry).
- **Wired into exactly one write path**, not every adapter:
  `archive/db/crud.py`'s `_find_or_create_page()` (both the create and
  update branches) -- matching the plan's "enrichment phase, not
  per-adapter" design. `app/db/crud.py`'s `log_resolution()` also gained
  a diagnostic-only `jurisdiction_confidence` (both tables, per the
  user's call) without ever rewriting the resolver's own raw logged
  value -- the Archive is the only place a repaired/split jurisdiction is
  actually written.
- **Schema**: `meeting_body` + `jurisdiction_confidence` on
  `archive/db`'s `meeting_pages`; `jurisdiction_confidence` on `app/db`'s
  `meeting_resolutions`. Both Alembic migrations hand-written (not
  autogenerated, to avoid connecting to production `DATABASE_URL` for a
  schema diff) and verified upgrade+downgrade clean against fresh local
  SQLite databases before being trusted.
- `get_page_by_slug()` updated to return the two new fields -- caught
  proactively by noticing this function has *already* shipped the exact
  same "field exists on the model but the hand-built response dict
  doesn't include it" bug once before (the `platform` key, see
  BACKLOG_DONE.md) and checking for it this time instead of repeating it.
- **Explicitly not done this slice**: display-layer wiring (`/meetings`
  listing, `/coverage`, saved-items, and the meeting page template all
  build their own separate dicts elsewhere in `archive/db/crud.py` that
  don't include the new fields yet -- a UI/UX decision, not just plumbing,
  deliberately left for its own pass); wiring the chain extractors
  (stop-rule/subdomain-validated/etc.) into Swagit or generic_fallback;
  the targeted ~90-page backfill.
- Tests: 14 new (11 pure-function in `test_jurisdiction_enrich.py`, 3 real
  end-to-end integration tests against the isolated SQLite fixture DB in
  `test_ingest_promotion.py`, reusing the Hercules/Santa Clara real
  examples). Full suite green throughout (750 tests at time of writing).

**Slice 3 (same branch)**: promoted the tournament's two winning
extractors into a shared chain (`jurisdiction_enrich.extract_jurisdiction_chain()`)
and wired it into the two priority adapters -- Swagit and
generic_fallback, the highest-volume adapters that never called into
this module at all before.
- Three tiers, tournament-ranked: `_stoprule_extract()` (body-text "City
  of X" walk with the period+capitalization combined stop rule --
  361/649 table-valid in the tournament, beating the shipped Granicus
  regex's 318 outright and eliminating bleed almost entirely, 68→2
  trim-needed), `_capitalization_walk_extract()` (a reimplementation of
  PrimeGov's own tag-bounded regex -- 326/649 -- deliberately NOT
  imported from `app.platforms.primegov`, since that adapter's resolve()
  path stays untouched this round and importing a live method from it
  would create exactly the coupling that deferral is about avoiding),
  `_validated_subdomain_extract()` (raw-label-then-wordninja-split,
  Census-validated before ever being offered -- 416/649 with zero
  garbage, vs. 408/229-garbage for the shipped always-guess wordninja
  fallback; fixes Galesburg specifically, since wordninja's own split
  "Gales Burg" never validates while the raw label does). Every
  candidate is run through the existing `enrich_jurisdiction_text()` for
  state resolution before being returned, reusing its domain/name/ZIP
  disambiguation rather than duplicating it.
  `clerkbase_slug`/`fallback_titletag` (tournament losers -- no
  generalization / zero unique coverage) are deliberately excluded.
- Swagit's `resolve()` calls the chain only when its own `<title>`-tail
  parse found nothing. generic_fallback's `_backfill_metadata_from_page()`
  calls it only when neither confirmed `<title>`-tag shape matched AND
  `resolved.jurisdiction` is still empty -- preserving the existing
  "jurisdiction always prefers a matched title-tag over a YouTube
  uploader name" override behavior exactly as before.
- Deliberately duplicates (doesn't import) Granicus's
  `US_STATE_ABBREVIATIONS` set and reimplements PrimeGov's jurisdiction
  regex, both to avoid a platforms -> utils reverse import (both
  `granicus.py` and `primegov.py` already import this module).
- Tests: 9 new (6 pure-function chain tests in
  `test_jurisdiction_enrich.py` covering all three tiers plus a
  decline-rather-than-guess case; 2 real `resolve()`-level tests in
  `test_swagit.py`; 1 in `test_generic_fallback.py`), all built from the
  same real Hercules/Galesburg/San-Diego examples already verified
  earlier in this plan -- no new synthetic shapes invented. Full suite
  green throughout (759 tests at time of writing).
- **Still not done**: display-layer wiring, the targeted ~90-page
  backfill.

**Slice 4 (same branch)**: display-layer wiring for `meeting_body`
(`jurisdiction_confidence` deliberately NOT surfaced anywhere in the UI
-- see below).
- `archive/db/crud.py`'s remaining response-dict builders now select and
  return `meeting_body` alongside `jurisdiction`: `list_pages()` (the
  `/meetings` listing's own query) and `list_saved_items()` (which joins
  `MeetingPage` for its saved-meetings display fields). `get_page_by_slug()`
  already had it from Slice 2.
- Three templates render it, each right next to the existing jurisdiction
  display, separated by " · ": `meeting_page.html` (the individual
  meeting's byline), `meeting_list.html` (`/meetings` per-row), and
  `saved_items.html` (My Saved Items). Verified live in-browser (not just
  via the JSON response) against a real seeded page using the Housing
  Authority of Santa Clara example already used in
  `test_ingest_promotion.py`: both `/m/{slug}` and `/meetings` correctly
  render "Housing Authority · County of Santa Clara · 2026-08-10".
- **`/coverage` and `feed.xml` deliberately left unwired** -- judgment
  call, not an oversight. `/coverage`'s examples exist to demo "does this
  platform correctly extract a jurisdiction," a claim `meeting_body`
  doesn't bear on; the RSS feed's titles are kept intentionally short for
  syndication. Both stay wired to `jurisdiction` alone.
- **`jurisdiction_confidence` intentionally has zero UI surface**, still.
  The tiers below "authoritative"/"validated"/"repaired" all mean "kept
  as extracted, not specially trusted" -- "unverified" in particular
  covers the *correct*, common case of a real entity type no national
  table will ever contain (school districts, MPOs, transit authorities --
  see this file's own "Deprioritized ideas" cross-reference in
  BACKLOG.md). Showing users a "low confidence" badge on those would be
  actively misleading, not informative -- confidence is a diagnostic
  field for the backfill/future admin tooling, not a public trust signal.
- Tests: 2 new real end-to-end integration tests
  (`test_list_pages_search.py`, `test_saved_items.py`), same Santa Clara
  Housing Authority example, confirming the field survives both read
  paths and not just `get_page_by_slug()`. Full suite green throughout
  (761 tests at time of writing).
- **Still not done**: the targeted ~90-page backfill.

**Slice 5 -- merge, migrate, and the real backfill (2026-08-15)**: the
whole branch (`jurisdiction-pipeline-r1`, 6 commits) merged to `main` via
[PR #56](https://github.com/mroconnell/rtr-deeplink/pull/56), production
Alembic migrations run for both services, and the backfill executed for
real against production. Full account, including a real deploy-pipeline
mistake caught mid-session, in `BACKLOG_DONE.md`'s
"Jurisdiction/title extraction pipeline" section.

**Workstream 1/2/4 real numbers, superseding this file's earlier estimate**:
the dry-run diff (computed against the tournament's cached HTML, not a
fresh fetch) found only **30** of 649 pages would actually change --
9 already-correct SLC rows (cosmetic reformat only, excluded from the
real backfill per the user's call), 21 real fixes (17 Granicus bleed
repairs, 3 Swagit blank-jurisdiction fills, 1 generic_fallback blank fill
-- Tucson). All 21 confirmed live in production Postgres and on
`redtaperecordings.com` after the fix -- e.g. Hercules now reads
"Hercules, CA" (was "Hercules. XIV. PUBLIC COMMUNICATIONS XV."), the
Santa Clara Housing Authority page now reads "Housing Authority · County
of Santa Clara, CA".

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

---

## Phase 1 — gov_id registry scoring (WO-98, 2026-09-02)

> **Numbers below are the first run's, kept for the record. The current
> ones are in "Phase 1b" at the end of this file** — a fix pass over the
> same branch, run against the same 5,929 rows.

Step 1 of `rtr-business/research/GOVERNMENT_IDENTITY_ARCHITECTURE.md` §6:
the registry data files and a pure resolver module
(`app/utils/gov_registry/`), **scored before any schema change**. Nothing
in this repo imports the package yet; `scripts/score_gov_registry.py` is
its only caller. No schema change, no production write, no Alembic
migration, and no change to any adapter's or `finalize_jurisdiction()`'s
behaviour — the resolver *calls* the enricher rather than replacing it.

Scored the way the 2026-08-15 tournament above was: against real data,
with the numbers stated before anything is built on them. Inputs:
**5,053** archived pages (metadata only, via `GET
/internal/export/pages`) and **876** distinct `(tenant, jurisdiction)`
pairs from rtr-discovery's ledger — 5,929 rows in total. Full sheets and
per-cut breakdowns in `reports/gov_registry_scoring_2026-09-03/`.

### Tier distribution

| tier | archive pages | ledger pairs |
| --- | --- | --- |
| pinned | 410 (8.1%) | 94 (10.7%) |
| registry | 3,743 (74.1%) | 731 (83.4%) |
| unverified | 673 (13.3%) | 51 (5.8%) |
| blank | 227 (4.5%) | 0 (0.0%) |

**4,719 of 5,929 rows (79.6%) got a national id** — a Census GEOID/FIPS,
a Census school-district GEOID, or a StatCan SGC code. The remaining
1,210 mint an `rtr:` id over **636 distinct governments**, and 227 rows
have no jurisdiction string at all (`rtr:unknown:<host>`).

### Merges and splits — the part that proves the design

**142 merges**: two or more of today's `/j/` hubs collapse into one
`gov_id`, retiring **289** hub pages' worth of fragmentation. **Exactly
13 of them are California counties** — which is what the architecture
doc predicted, unprompted, from a completely separate count of
`/state/california`. Others: `us:place:0667000` absorbs `ccs-f`,
`city-and-county-of-san-francisco` and `san-francisco-ca`;
`us:county:12095` absorbs `orange-county`, `orange-county-comptroller`
and `orange-county-fl`.

**50 splits**: one of today's hubs becomes several governments. Six of
them are the §1.3 mislabels being undone, which is the whole point:

| today's hub | becomes |
| --- | --- |
| `/j/los-angeles-ca` | LADWP + City of Los Angeles |
| `/j/los-angeles-county-ca` | LA Metro + Los Angeles County |
| `/j/san-diego-ca` | SANDAG + City of San Diego |
| `/j/indio-ca` | Coachella Valley Water District + City of Indio |
| `/j/tarrant-county-tx` | Tarrant County College District + Tarrant County |
| `/j/horry-county-sc` | Horry County Schools + Horry County |

### Government types, and the classifier disagreement

| gov_type | rows |
| --- | --- |
| municipality | 3,926 |
| county | 955 |
| other | 569 |
| township | 236 |
| school_district | 124 |
| special_district | 104 |
| state | 10 |
| court | 5 |

**583 rows** where the new `gov_type` disagrees with
`archive/utils/gov_classify.py`, the classifier driving the `/state/*`
headings today: 135 filed as cities that are counties, 46 as cities that
are special districts, 29 as counties that are school districts, 10 as
schools that are municipalities, 9 as cities that are state bodies. The
largest bucket (330 "city" → "other") is not a disagreement about a
*government* so much as about a bare, unclassifiable name —
`gov_classify` defaults to city, this defaults to `other` rather than
guessing.

### Canada

**415 of 450** Canadian rows (92.2%) got a StatCan id. The 35 that
didn't are school boards, conservation authorities and police services
boards, which have no SGC code by construction (decision D4 — SGC codes
subdivisions and divisions, not boards) and correctly mint `rtr:ca:`.
This is against **0 of 10** Canadian override rows carrying any code
before this work.

### Two corrections to the architecture doc, found by building against it

1. **§1.4 is wrong about one of its three examples.** It states that
   `discovery/feed/govtype.py` correctly classifies "Broward County
   Public Schools", "West County Wastewater District" and "Minnesota
   Senate". Running its own `_RULES` on 2026-09-02 returns
   `school_district`, **`county`**, `state` — the county rule's negative
   lookahead lists "water" but not "wastewater", so the middle one falls
   into the same bucket `gov_classify.py` puts it in. Corrected here and
   in the doc; `tests/test_gov_registry.py` pins the fix.
2. **The COG file's `CENSUS_ID_GIDID` cannot be an identity namespace.**
   Census stopped generating it in 2022 and has never published its
   segment layout (it does not even line up with FIPS — California rows
   start "05"). `cog_units.csv` therefore carries `CENSUS_ID_PID6` as a
   pure enrichment column, which is what D3 already provided for.

### Residual gaps, for Ryan before Phase 2

- **A state-less stored jurisdiction cannot be keyed nationally.** Most
  remaining splits are one government arriving twice — once with a state
  and once without (`/j/beverly-hills` → `rtr:us:xx:beverly-hills` +
  `us:place:0606308`). Phase 2's backfill should let a tenant's other
  pages supply the state before minting.
- **11 tenant hosts have sources that disagree** about which government
  they belong to. Neither is written; both are in
  `app/utils/jurisdiction_data/tenant_overrides_conflicts.csv` for
  review. A wrong pin is worse than no pin, because a pin is the one tier
  that overrides a working extraction.
- **Consolidated city-counties are only half solved.** San Francisco
  merges correctly onto its place GEOID; Nashville-Davidson still mints
  two ids ("Nashville-Davidson County" and "Nashville-Davidson
  metropolitan government") because neither spelling matches the county
  table and only the "(balance)" form matches the place table.
- **227 rows have no jurisdiction at all**, concentrated on Swagit school
  district tenants (`coppellisd.new.swagit.com`,
  `pelhampublicschoolsny.new.swagit.com`) — the same blank-jurisdiction
  family workstream 3 above already identified, now countable per host.

---

## Phase 1b — the fix pass (WO-98, 2026-09-02)

A second pass over the same branch, before Phase 2, against the same
inputs: 5,053 archived pages and 876 ledger pairs. Same constraints —
no schema change, no production write, nothing importing the package.
Report regenerated in place at `reports/gov_registry_scoring_2026-09-03/`
— **that directory holds the CURRENT run, not this one.** The report is
regenerated in place by every scoring pass and the directory was renamed
when Phase 2's last pass rolled past midnight; Phase 1's and Phase 1b's
numbers survive as the tables in this document, which is what the note at
the top of the Phase 1 section is about.

### The three targets

| check | Phase 1 | Phase 1b | target |
| --- | --- | --- | --- |
| rows on the county table whose raw name had a municipal type word | 26 | **0** | 0 |
| `rtr:us:xx:` / `rtr:ca:xx:` ids | 624 | **0** | 0 |
| pins sourced only from `auto_derived` | 447 | **0** | 0 |

National-id coverage went **79.6% → 83.0%** (4,919 of 5,929) on a
stricter definition: the Phase 1 headline counted an id as national
whenever it did not start with `rtr:`, which quietly included the new
empty-id `unresolved` rows. Canada went 92.2% → **88.6%** for the same
reason — the honest denominator grew as more Canadian rows became
reachable at all.

| tier | archive pages | ledger pairs |
| --- | --- | --- |
| pinned | 175 (3.5%) | 23 (2.6%) |
| registry | 4,013 (79.4%) | 799 (91.2%) |
| inferred | 7 (0.1%) | 2 (0.2%) |
| unverified | 235 (4.7%) | 12 (1.4%) |
| unresolved | 382 (7.6%) | 40 (4.6%) |
| blank | 241 (4.8%) | 0 |

`pinned` falls because 447 hosts lost a pin they should never have had;
`registry` absorbs them, which is the point — a table hit is evidence, a
machine-derived pin is not.

### What was wrong, and what fixed it

**1. A municipal name resolving to a county.** "City of Santa Clara",
"City of Riverside", "City of Maricopa", "City of Boise, ID", "City of
Waukesha, WI", "City of Greenville", "City of Santa Rosa" — each landed
on the same-named county, merging a city's pages into its county's hub.
That is worse than not resolving, because it looks resolved. The
general-purpose branch's bare-name county fallback is now gated on the
absence of a municipal type word.

Gating it immediately produced a second bug of the same shape: "City of
Santa Clara" stopped becoming Santa Clara County and started becoming
`us:cousub:3603365178` — **Santa Clara *town*, NY**. A cousub now has to
match the raw type word too.

**2. Place lookups that missed.**
- *Within-state place collisions.* Waukesha WI is a city (`5584250`) and
  a village (`5584275`) under one normalized key, so the exactly-one rule
  declined and the county caught the fall. The raw type word now breaks
  the tie inside the place table, the same way it already did between
  place and cousub. Two candidates and no type word still returns
  nothing.
- *Census official names.* Boise is "Boise City city"; Louisville is
  "Louisville/Jefferson County metro government (balance)"; Nashville is
  "Nashville-Davidson metropolitan government (balance)"; DC was missing
  from the table entirely (FUNCSTAT `N`, kept now by GEOID with the
  reason recorded — the other three `N` rows nationally are genuinely
  defunct, and Louisville city in particular must stay out or it collides
  with the metro government). Handled by reusing the enricher's own
  `_QUERY_GOVERNMENT_TYPE_RE` and slash-spacing normalization, a
  county→place fallback restricted to the 10 consolidated FUNCSTAT `B`/`F`
  rows, and a **curated alias** pass. Both Nashville tenants now land on
  `us:place:4752006`, Louisville on `us:place:2148006`, DC on
  `us:place:1150000`.
  Curated aliases live in their own `curated_governments.csv` and are the
  only aliases ever looked up: the `aliases` column on a *generated* row
  records what happened to resolve there, and looking those up would make
  a wrong resolution self-reinforcing.

**3. No id is minted with an unknown state.** The state is now recovered
from the tenant — the enricher's validated subdomain reading,
`_KNOWN_DOMAINS`, then `tenant_hints.csv` — **before** the national
lookup, not merely before minting. That ordering matters and was itself a
bug found mid-pass: a stateless name is looked up nationally, where the
place table is often ambiguous while the county table is not, so
`riversideca.granicus.com` stored "City of Riverside" on one page
(→ `us:place:0662000`) and a bare "Riverside" on the next
(→ `us:county:06065`). One tenant, one government, two ids. 458 rows now
carry a state recovered this way.

Two new tiers follow. **`inferred`** is the same-tenant consistency rung:
when every other resolved row for a host agrees on one government, adopt
it (9 rows — low, because rung 3b already recovered most of them by
state). **`unresolved`** is a real government name with no state and
nothing to key it by: 422 rows, listed in `unresolved.csv` for a pin, and
deliberately **not** minted. Their hosts are mostly shared ones where a
tenant state is meaningless — `youtu.be` (28), `www.youtube.com` (13),
`videoplayer.telvue.com` (8).

**4. Seeding no longer launders machine guesses into pins.** 447 hosts
whose only evidence was rtr-discovery's `tenants.jurisdiction_override`
are out of `tenant_overrides.csv` and into a new `tenant_hints.csv` that
the resolver reads **for state only, never for a gov_id**. That is where
"S Fw, MD", "Mw Rd", "Ps C, FL", "Psr C 2", "Ride Uta" and "Tampa D"
came from. Pins: 767 → 330, of which 0 are auto-derived-only.

Conflicts fell 11 hosts → **1**. Ten were never disagreements: an
`unresolved` candidate has no gov_id and asserts nothing, so it no longer
counts as a competing claim. The one that remains,
`uatccta.primegov.com`, is listed under El Cerrito **and** San Pablo in
the upcoming roster — a real shared multi-government tenant (§1.5), not a
conflict. It gets no pin and is recorded as the first case wanting a
`match` discriminator.

**5. Display.** One parenthetical form for within-state disambiguation —
"Cottage Grove (town), WI" / "Cottage Grove (village), WI" — so both
sides of a shared name read the same way; the old suffix form ("Cottage
Grove Town") read as a different name rather than as a disambiguator. An
uncontested township keeps §4's suffix form ("Chesterfield Township,
MI"). Census's "(balance)" and government-type phrases are stripped from
display names ("Nashville-Davidson, TN"). DC and Louisville are
`municipality`, not `other`.

### One more mislabel found, from the export itself

`imperialid.granicus.com` resolved to **Imperial County, CA**. Its one
archived page has slug `imperial-iid-bod-regular-meeting-january-21-2025`
— Imperial Irrigation District, Board of Directors. The "id" in the
subdomain is the district, not Idaho, and its stored jurisdiction is a
bare "Imperial", which matched the nationally-unique county while the
places named Imperial were ambiguous. Pinned, with that slug as the
evidence. Same shape as §1.3's nine.

### Merges and splits now

**169 merges** over 341 hub pages, and the bad ones are gone: Santa
Clara, Riverside and Maricopa each now have a *city* merge and a
*county* merge, separately and correctly, instead of one hub swallowing
the other. **33 splits**, down from 50, and the remainder are real:
`/j/portland` becomes three governments in OR, ME and TX; `/j/portage`
three in IN, MI and WI; and the §1.3 agency splits all stand.

### Addendum — the minting gate and the pin worklist

**6. A string only mints an id if it looks like a name.** Minting turns a
string into an identity, and doing that for a subdomain fragment creates
a permanent, authoritative-looking id nobody can ever look up. Three
tests, all of which must pass: at least one 4+-letter token that occurs
in a real government's name; not every token under 4 letters; not a
station callsign. A failure is tier `unresolved` with the raw string kept
in `evidence`, so no information is lost and a human pin still has
everything.

"A real government's name" is a *vocabulary*, not a dictionary —
20,686 words from the national tables plus `cog_units.csv`'s 90,837 real
US government names. That pairing is what makes it work: the place tables
know "Wichita" and "Tampa" but not "authority", "commission",
"irrigation" or "wastewater", so a vocabulary built from them alone would
reject most real agency names. A general English dictionary would fail
the other way — it accepts "ride" and rejects "sandag".

**32 rows reclassified**, over 30 distinct hosts: granicus 18, escribe
10, cablecast 3, swagit 1; 22 US and 10 Canadian. Every one is
subdomain-derived junk — `'Llbc'`, `'Notl'`, `'Cofs'`, `'Nsb'`,
`'Ps C, FL'`, `'S Fw, MD'`, `'Oneinvestmentprogram'`, `'La'`. Minted
governments fell 588 → 556 rows with no real name lost: "West County
Wastewater District", "Imperial Irrigation District", "Metropolitan
Airports Commission", "Toronto and Region Conservation Authority" and
"Leduc, AB" all still mint.

**7. `pin_worklist.csv` — 369 hosts, 420 rows.** Every tenant with no
government, grouped by platform with eScribe, Cablecast, Swagit and
TelVue first (the four whose landing page reliably names its customer),
each with a landing URL to fetch once and read the organisation name out
of the header — the way `jurisdiction_overrides.csv`'s
`visual_confirmed` rows were made by hand. Platform spread: granicus 114,
youtube 102, cablecast 61, telvue 53, swagit 38, escribe 35.

The eScribe block is the highest-yield: `pub-cambridge`, `pub-london`,
`pub-halifax`, `pub-hamilton`, `pub-brucecounty`, `pub-lincoln` are all
real Canadian governments that are `unresolved` only because no province
could be recovered — a single fetch settles each.

TelVue rows carry the org token from the URL path as `match_value`
(53 distinct tokens), because every TelVue customer shares
`videoplayer.telvue.com` and a host-level pin would be wrong for all of
them. One of the 53, `GNduNoua2rBThhw6N4PRP9OCSPf6B2ru`, is already
identified by hand in
`rtr-business/research/telvue_org_tokens.md` (Centre County PA) — a
useful cross-check that the extracted token matches that file's format,
and 12 of the 53 already have an answer waiting there.

### Step 8 — the landing-page sweep

278 hosts fetched once each, politely paced, read-only
(`scripts/sweep_tenant_landing_pages.py`; YouTube's 117 rows skipped, and
counted as skipped rather than failed, because the host is shared and the
tenant is the channel id). 223 landing pages came back. **7 pins
written**, every one corroborated by its own hostname:

| host | government | the page reads |
| --- | --- | --- |
| `cityofnsb.granicus.com` | `us:place:1248625` | "New Smyrna Beach FL" |
| `eastvale.granicus.com` | `us:place:0621230` | "Eastvale, CA" |
| `nrhtx.granicus.com` | `us:place:4852356` | "North Richland Hills TX" |
| `pvestates.granicus.com` | `us:place:0655380` | "Palos Verdes Estates" |
| `sanantonioisd.granicus.com` | `us:sd:4838730` | "San Antonio Independent School District" |
| `sandyutah.granicus.com` | `us:place:4967440` | "Sandy City, UT" |
| `mi-caledoniachartertownship.civicplus.com` | `us:cousub:2615512520` | "Caledonia Charter Township, MI" |

Still unresolved, by platform: granicus 106, cablecast 61, escribe 41,
swagit 39, iqm2 5, civicclerk 4, unknown 4, telvue 2, and one each of
castus, champds, townhallstreams, vimeo. Of those, 39 cablecast and 14
granicus hosts were unreachable at all; the rest served a page that names
nobody.

**The first run of this sweep produced 12 pins and six of them were
wrong.** Worth recording, because the failure is instructive and it is
the exact thing this whole scheme exists to prevent:

    'Section View- Live on website'       -> a Minnesota township
    'Fullerton Public - Powered by .com'  -> Fullerton, NEBRASKA
                                             (the tenant is Fullerton CA)
    'Midland City Council , Summaries &'  -> Midland, ALABAMA
    'Oregon Metro Council - New View'     -> Oregon County, MISSOURI
    'Council'                             -> Council, IDAHO

The extractor was splitting page titles on separators and the acceptance
test was "does this resolve to a non-`rtr:` id". The resolver normalizes
hard — that is its job, and it is what lets a real page's "County of
Fresno, CA" reach `us:county:06019` — so handed a title fragment it
normalizes just as hard and finds a nationally-unique token. Every one of
those would have been written `authoritative`, the one tier that
overrides a working extraction.

The fix is a rule strict enough to be boring: **the candidate, with any
trailing state stripped, must EQUAL one of the government's own names**
(the national table's spelling or this repo's display form, compared the
way the tenant-consistency rung compares names), and a bare generic word
("Council", "Board", "Default") is never a candidate at all. Re-derived
offline from the candidates the run had already recorded — no site was
fetched twice — it rejects all six wrong pins, keeps all six right ones,
and turns "Palos Verdes Estates - Palos Verdes Estates Content" into the
clean fragment beside it. It costs coverage on purpose: Fullerton CA's
page never plainly says "City of Fullerton", so this method honestly
cannot settle that host.

**A functional bug fell out of writing the pins**, caught by an existing
test: `_pinned()` looked its `gov_id` up in `governments.csv` alone and
fell through silently when it missed — and that file is a generated
snapshot of what a scoring run resolved *to*, so a pin naming a
government no page has reached yet is absent from it by construction.
All seven new pins would have been ignored, with nothing saying so. It
now derives the row from the national tables, and the scorer seeds every
pinned id into `governments.csv` as well.

**And the worklist's own ordering note is wrong.** It calls eScribe,
Cablecast, Swagit and TelVue "the four whose landing page reliably names
its customer". Measured: Cablecast does (in `og:site_name` *and*
`<title>`). Granicus, which the note omits, does — on
`ViewPublisher.php?view_id=N`, not the root; that is where every pin
above came from. eScribe names it **nowhere**: `Meetings.aspx` is titled
"Meetings" and the only candidate is a logo whose alt text is the literal
string "Organization Logo". Swagit's root is "SwagitAdmin", CivicClerk's
is "Public Portal • CivicClerk". So the block the report called
highest-yield — 41 eScribe hosts including `pub-cambridge`, `pub-london`,
`pub-halifax`, `pub-hamilton` — cannot be settled this way at all, and
wants the per-platform work `BACKLOG.md` now carries.

### Still open for Phase 2

- **422 `unresolved` rows want pins**, concentrated on shared hosts
  (`youtu.be`, `videoplayer.telvue.com`) where no tenant-level state
  exists. These are the rows a human list would fix fastest.
- **`uatccta.primegov.com` needs the first real `match` discriminator** —
  a path prefix or query parameter separating El Cerrito's meetings from
  San Pablo's.
- **241 rows still have no jurisdiction string at all**
  (`rtr:unknown:<host>`), concentrated on Swagit school-district tenants.
- A bare name with no type word and no tenant state can still reach the
  county table ("Waukesha" alone). The gate is on the municipal type
  word, as specified; the tenant-consistency rung is what catches these
  in context.

---

## Phase 2 — `gov_id` on `meeting_pages` (WO-99, 2026-09-02)

`GOVERNMENT_IDENTITY_ARCHITECTURE.md` §6's rtr-deeplink block, shipped.
The columns, the hubs, the override endpoint and the backfill; the same
5,053 archived pages and 876 ledger pairs as Phase 1/1b, so every number
below is comparable to the ones above.

**Confirmed before touching anything**: re-running
`scripts/score_gov_registry.py` against the committed registry
reproduced the merged Phase 1b report **byte-for-byte across all 12
files**, and `git log` shows no commit has touched
`tenant_overrides.csv` or `governments.csv` since the Phase 1 merge — so
Phase 2 started from exactly what was reviewed. (If corrections were made
by hand, they never landed in the repo.)

### The numbers, Phase 1b → now

| check | Phase 1b | Phase 2 |
| --- | --- | --- |
| national id | 83.0% | **83.7%** |
| Canadian rows with a StatCan code | 88.6% | **95.0%** |
| merges (hub pages collapsed) | 169 (345) | **179 (365)** |
| splits | 32 | **30** |
| distinct minted `rtr:` governments | 320 | **267** |
| strings rejected as "not a name" | 32 rows | **17 rows** |

| tier | archive pages | ledger pairs |
| --- | --- | --- |
| pinned | 181 (3.6%) | 26 (3.0%) |
| registry | 4,034 (79.8%) | 803 (91.7%) |
| inferred | 12 (0.2%) | 2 (0.2%) |
| unverified | 137 (2.7%) | 2 (0.2%) |
| unresolved | 448 (8.9%) | 43 (4.9%) |
| blank | 241 (4.8%) | 0 |

Coverage moved less than the Canadian figure because two of the fixes
below *reduce* it on purpose: declining a stateless name that is
ambiguous across the border, and refusing to mint for a bleed page, both
trade a resolved-looking row for an honest gap on the pin worklist.

### The seven residuals from the 1b review

Each was reproducible from `sheet_archive.csv`, and each has a test.

- **(a) Tenant consistency, guarded.** Adopts the tenant's dominant
  registry/pinned `gov_id` only when the base names agree with spacing
  and punctuation stripped, and the states do not contradict. The
  unguarded 1b pre-pass filed `dcccd.new.swagit.com`'s "City of Dallas"
  bleed page under Duncanville; the state half is what stops
  `juneauak.portal.civicclerk.com`'s "Juneau, AK" collapsing into the two
  "Juneau, WI" rows beside it, where the names agree perfectly. Hosts
  carrying more than one `gov_id`: **75 → 48** of 2,375, counted across
  both input sets and excluding `rtr:unknown:`. (The brief's "85 of
  2,254" is a differently-scoped count of the same thing; 75 is what the
  committed Phase 1b report gives under this definition, and the two
  figures here are measured the same way as each other.)
  The pre-pass also stopped requiring unanimity, which was false exactly
  when the rung was needed — `milwaukee.granicus.com` holds a minted id
  *beside* its real one, and that is the fragmentation.

  One trap, worth knowing about because it is the same shape as the
  `curated_aliases()` rule: the guard passed on
  `winston-salem.granicus.com`'s "City of Lees Summit" bleed page,
  because `governments.csv` carried that string in Winston-Salem's
  `aliases` — written there by the very unguarded pass being replaced. A
  generated row's aliases record what previously resolved there, so
  reading them back makes a wrong resolution self-reinforcing. Only
  curated rows' aliases count now.

- **(b) Minting gate.** A name that matches a national-table row once
  spacing and punctuation come off resolves instead of minting: "Gales
  Burg" → Galesburg, IL. Only with a state in hand, only when minting is
  the alternative. It also recovered four real run-together Canadian
  names the gate had been declining as junk — "Stjohns" → St. John's NL,
  "Northcowichan", "Bradfordwestgwillimbury", "Espanol A" → Espanola ON.

- **(c) "Name, X County, ST".** "City of Sunset Valley, Travis County,
  TX" and "Town of Amherst, Erie County, NY" — the only two strings of
  this shape in the export — resolve the place, with the county recorded
  in the evidence as enrichment. Gated on the prefix carrying a municipal
  type word, so the rule cannot eat the tail of "Board of Supervisors,
  Fresno County".

- **(d) Canada.** The `ca:cd` fallback now has the same municipal-type-word
  gate the US county table already had: "Town of Yarmouth, NS" is
  `ca:csd:1202006`, not the Yarmouth census division. A **name-first**
  tie-break runs ahead of it, because "Leduc County" and "Leduc" are two
  different names that `_normalize_name()` flattens onto one key, not one
  name shared by two governments — without it the type-word rule would
  have traded one fragmentation for another (City of Leduc resolving
  while a bare Leduc minted). This is most of the 88.6% → 95.0% jump.

- **(e) Honolulu.** Pinned to `us:county:15003`, authoritative: Hawaii
  has no separate municipal government there, and the same Granicus clip
  2444 is archived twice on that host, once as "County of Honolulu." and
  once as "City of Honolulu". A curated row names it "City and County of
  Honolulu".

- **(f) Bleed pages.** A general-purpose name whose only state came from
  its tenant, on a tenant whose government it does not name, is left
  `unresolved` and listed rather than minted. "City of Lees Summit" on a
  North Carolina tenant was minting `rtr:us:nc:lees-summit` — an
  official-looking id for a government that does not exist in that state.
  Non-place types are exempt: D2 says a housing authority disagreeing
  with its host city is the normal case, not a bleed.

### Four defects found while building, none of them on the list

- **A bare `port` token** in the special-district classifier put the
  place tables out of reach for **24 rows over 11 real municipalities**
  (Port Townsend WA, Port Moody and Port Coquitlam BC, Port Hope and Port
  Colborne ON, North Port and Port Orange FL, Port St. Lucie, Port Arthur
  TX, Port Chester NY), every one minting an `rtr:` id for a government
  the tables hold. Same shape as the "wastewater" defect §1.4's
  correction records. Real port agencies still classify as districts.

- **"Nationally unique" meant "unique in the United States."**
  `country_for_state("")` is `"us"`, so a stateless name was never
  checked against the Canadian tables. **16 rows**, and the wrong ones
  are not subtle: Abbotsford BC as Abbotsford WI, Edmonton AB as Edmonton
  KY, Niagara Falls ON as Niagara Falls NY, Langford and White Rock BC as
  two South Dakota places, Port Hope ON as Port Hope MI. Now declines —
  which costs a pin-worklist row and prevents a wrong-country hub. Three
  of the 16 (Nampa ID, New Carlisle OH, Hawarden IA) really are the US
  one and are the price; each has a real Canadian namesake, so the
  ambiguity is genuine.

- **"Boise, ID" resolved to Boise COUNTY.** Census spells the city "Boise
  City city", so the place lookup misses and the bare-name county
  fallback answered before the curated alias that exists for exactly this
  name. "City of Boise, ID" was correct the whole time, because its type
  word gates that fallback off — so one city had two governments
  depending on how a page spelled it. Caught by an unrelated hub test.

- **"City of Al"** on `allentownpa.granicus.com` — a truncated "City of
  Allentown" whose stray "Al" the bare-state-suffix rule read as Alabama,
  leaving the name "City of" and minting `rtr:us:al:city-of`, displayed
  as "City of, AL". Every step individually defensible, which is why the
  gate is on the outcome: a name made only of type words is not a name.

### And two only the in-browser check could find

CLAUDE.md's "verify in-browser, not just via the API" earned itself again
here — neither of these would have failed a test.

- **82 of 751 generated hub-slug aliases redirected to hubs that do not
  exist.** A row the resolver leaves `unresolved` has no `gov_id` and so
  no hub, but the alias writer was still emitting a redirect for it:
  `/j/cottage-grove` → `/j/city-of-cottage-grove`, a 301 to a 404, which
  is strictly worse than the 404 it replaced. 751 → **702** (the count moved again when the seven new pins resolved seven more hosts).

- **A state government could never appear on its own state page.**
  Decision D1 makes the State of California one government whose Senate
  and departments are `meeting_body` rows under it, so its display name
  is "State of California" — with no ", CA" suffix for `/state/*`'s
  anchored LIKE to anchor on. The "State government" heading this same
  change introduced was therefore unreachable.

### Still open

- **448 `unresolved` rows and 241 blank ones** want pins. The landing-page
  sweep (step 8) is the method, and it turns out to work for fewer
  platforms than `pin_worklist.csv` assumed — see `BACKLOG.md`'s three
  new entries for what each platform actually returns and what would
  settle the rest.
- **A minted government's page and its hub show two different names**
  (the Santa Clara housing authority). Cosmetic, bounded, and logged.
- **`uatccta.primegov.com`** is still the first real multi-government
  tenant with no `match` discriminator.
