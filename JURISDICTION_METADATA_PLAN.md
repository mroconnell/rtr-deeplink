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
per-cut breakdowns in `reports/gov_registry_scoring_2026-09-02/`.

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
