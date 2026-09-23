# Context pipeline implementation plan

Prepared September 23, 2026. Approved by Ryan and implemented as WO-1014. See `CONTEXT_CANDIDATES.md` for the delivered workflow and verification. The sections below preserve the design and agent work split.

I reviewed the September 22 handover in `rtr-business/research/RTR_Context_Pipeline_Fable_Handover_2026-09-22(1).docx`, the live Context feed and a published entry, and freshly fetched `origin/main` at `338e745`. The open working branch predates Context and contains unrelated edits. Implementation must start from current main in isolated worktrees.

**Recommendation.** Build Milestone 1 as a small research intake and review tool. Keep Muse as a replaceable research source and keep publication editorial. The useful improvement is less repeated checking and copying per worthwhile post. Volume is not the goal.

The live examples show why this matters. The San Diego entry connects a satirical speech to the recording and transcript. The Indianapolis examples include an audience camera angle and footage after the official recording ends. A correct meeting association does not necessarily mean the social footage has an exact counterpart in the official recording. An accurate timestamp also does not establish the truth of an allegation made by a speaker.

The four proposed benefits are credible product goals, with different measures:

| Benefit | What to measure |
| --- | --- |
| Help people understand a circulated clip | Verified meeting links; usable explanation of what preceded or followed it; readers opening the full recording |
| Add archive breadth | Distinct governments newly represented by a verified, ingested meeting; count only after ingestion |
| Guide readers to significant moments | Published entries appearing on their associated meeting pages; already supported |
| Improve discovery | Indexable Context pages, search impressions and visits; do not substitute page count for evidence of reach |

Original research and useful explanations are consistent with [Google's guidance on helpful content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content). Search traffic remains an outcome to measure, not a promised result of automation. No new analytics system is part of Milestone 1.

**What the repository already provides.**

- Archive owns `MeetingPage`, `MeetingPageUrlAlias`, `TranscriptVersion`, `TranscriptionJob`, and `ContextEntry` in `archive/db/models.py`. Resolver and Archive have separate databases. Candidate storage belongs in Archive.
- `archive/main.py` renders Context pages and handles token-protected writes. `app/main.py` exposes explicit proxies on the public domain. `app/archive_client.py` relays authenticated operations between them.
- `archive/utils/context_links.py` already canonicalizes social URLs, supplies stable post keys, and parses RTR meeting links. `archive/utils/context_editors.py` supplies the existing editor allowlist.
- Public entries have publication states `draft`, `published`, and `hidden`. Their moment labels are `exact`, `approximate`, and `related`. There is no `undecided` public label. Unknown candidate values must remain unknown.
- The existing editor requires a summary even for a draft. Raw research rows should therefore not be forced into editorial drafts.
- Current main already supplies Context mentions on meeting, government, and state pages; canonical entry permalinks; transcript excerpts; structured data; RSS; and sitemap inclusion. The live San Diego permalink shows the excerpt and government/state links. Current main gates Context indexing on five published entries. No redesign of these surfaces is needed for intake.
- `archive/db/crud.py:lookup_page_for_url()` checks stored URL aliases and normalized source URLs. Ingestion also uses `(platform, external_id)`. Platform identifiers must retain their existing tenant namespace: two Granicus cities can have the same numeric clip ID.
- Existing ingest goes through platform resolution and Archive `/internal/ingest`. Transcription uses the existing Archive job records and `worker/main.py`, plus a separate local transcription path. Search uses stored transcript versions and the existing full-text search implementation. None needs replacement for this milestone.

The handover's direction is sound. Its main corrections are placement under Archive, the actual moment labels, separation of research from editorial drafts, and the fact that several reader-facing benefits are already built. Its nine proposed states also mix three separate questions: meeting lookup, moment verification, and publication.

**Milestone 1 boundary.**

Deliver: candidate file → validated research records → read-only exact-meeting lookup → explained next action → private queue.

Import may create candidate records and research observations only. Recheck may update their lookup results. This work must not resolve remote meeting pages, fetch social posts, download video, enqueue transcription, ingest meetings, create editorial entries, or publish. No scheduler, job broker, new service, or AI API is needed.

**Placement and files.**

Use `archive/context/` as the new package. It sits beside Archive's existing domains and can grow later. Do not move the working public Context implementation simply to obtain a top-level directory named `context/`.

| Files to add or change | Responsibility |
| --- | --- |
| Add `archive/context/__init__.py`, `schemas.py` | Versioned candidate input and lookup-result contracts |
| Add `archive/context/importer.py`, `store.py` | Normalize input, preserve observations, deduplicate, and persist candidates |
| Add `archive/context/lookup.py`, `status.py` | Bounded database lookup, evidence comparison, and next-action rules |
| Add `archive/context/routes.py` | Candidate-only API and editor queue routes; reuse current auth patterns |
| Change `archive/db/models.py`; add one revision in `archive/alembic/versions/` | Candidate and observation tables, constraints, and indexes |
| Change `archive/main.py` | Register candidate routes before the existing Context permalink catch-all |
| Change `app/main.py`, `app/archive_client.py` | Explicit queue proxy and authenticated editor recheck relay |
| Add `archive/templates/context_candidates.html`, `archive/static/context_candidates.js`; small change to `context_new.html` | Paginated private queue, detail/evidence view, recheck action, and editor navigation link |
| Add `scripts/import_context_candidates.py` | CSV/JSON input, preview by default, explicit apply, bounded batches and run report |
| Add `tests/test_context_candidate_import.py`, `test_context_candidate_lookup.py`, `test_context_candidate_status.py`, `test_context_candidate_routes.py` | Import, lookup, state, authentication, and isolation tests |
| Add `tests/fixtures/context_candidates/` | Reviewed real candidate examples; exact source mapping depends on the actual Sheet |
| Update `README.md` and this plan | Operator instructions, approved scope, and completion evidence |

Existing public Context CRUD and URL helpers remain in place and are reused. Avoid enlarging `archive/db/crud.py` with the new subsystem. Shared helper extraction is allowed only where needed, with regression coverage. No platform-adapter changes are planned.

**Candidate storage and import contract.**

Use two small tables in the existing Archive database:

1. `ContextCandidate`: one row per canonical social-post key, uniquely constrained. Store social URL/network/poster, nullable proposed jurisdiction/state/date/body, proposed recording and RTR links, proposed timestamp, draft title/summary, research notes, nullable associated meeting FK, nullable existing Context-entry FK, lookup outcome/evidence, next action, checked time, and record version. Proposed facts and computed lookup results are separate fields. Preserve missing fields as nulls. Store timestamp seconds as a number while retaining the original input in the observation.
2. `ContextCandidateObservation`: original provider payload, provider name, stable source-record key, source location, content hash, and receipt time. Unique `(provider, source_record_key, content_hash)` makes an unchanged replay a no-op while retaining changed research. Attach each observation to its candidate. Do not use a Sheet row number as the permanent identity.

Reuse `parse_social_url()` for the candidate key. Distinct social posts about the same meeting stay distinct. If the post is already in `ContextEntry`, link to that record and display its current publication state; never overwrite it.

The importer accepts one documented input shape from CSV or JSON. A small source mapping converts the actual Sheet columns into that shape. Muse names and Sheet column labels stay out of lookup and storage logic. Start with a Sheet export; a later read-only Sheets adapter can call the same importer without altering the core.

Validate row sizes, types, HTTP(S) URLs, date precision, and timestamps before applying. Report malformed rows with source references. Ambiguous dates remain unresolved. Never silently trim research into the public title/summary limits; show editorial-length issues separately. Treat all imported text as data and escape it in HTML. Do not render arbitrary source HTML or fetch supplied URLs during import.

Preview reports intended additions, changes, duplicates, and rejected rows. Apply commits per candidate and uses database uniqueness constraints to survive retry or concurrent imports. Changed source claims preserve the old observation, invalidate stale lookup results, and trigger re-evaluation. Keep the latest observation from each source active. Different providers supplying contradictory meeting claims force conflict review; import order must never decide which claim wins. Prior observations remain available. Existing editorial associations are untouched. A manual candidate-confirmation action is deferred beyond Milestone 1. Use optimistic concurrency: a stale recheck cannot overwrite a newer import.

**Exact meeting lookup.**

Return a typed outcome: `matched`, `not_found`, `ambiguous`, `conflict`, or `error`, plus method, evidence, possible page IDs, checked time, and a snapshot of the page identity fields and `updated_at` checked. Do not add a version column to `MeetingPage`.

1. Parse an explicit RTR meeting link with the existing parser, then load its page. A valid-looking slug alone is not a result.
2. Check the proposed official-recording URL against Archive's URL aliases and normalized source URLs. Use Archive's conservative normalizer; do not discard arbitrary query parameters.
3. Where a supplied URL contains an unambiguous identifier with an already verified parser/fixture, check the existing `(platform, external_id)` representation. This is pure parsing, with no remote fetch. An unsupported wrapper remains unresolved; do not invent delegated identities or identifiers from Muse's prose.
4. Combine all available direct identifiers. If they point to different meetings, report conflict rather than accepting the first result. Detect multiple records instead of silently selecting one.
5. Compare available government, meeting date, and body evidence. A blank is missing evidence, not agreement or disagreement. Conflicting assertions go to review; they do not repair Archive records automatically. Respect consolidated-government identities and shared-host rules from `docs/COVERAGE_HANDOVER.md`.
6. A government/date/body query may suggest a bounded list of possible meetings. It cannot certify an exact match, even if only one row is returned. Meeting-body coverage is incomplete, and multiple sessions can occur on the same day. Store the suggestion and its reason for research follow-up.

The existing resolver client `app.archive_client.lookup()` returns `None` for non-200 responses and an unconfigured Archive. That behavior suits the resolver's fallback flow but not this queue. Use Archive-side queries with explicit error handling; importer/API failures must remain errors. A failed query must never mean ingestion is needed.

A URL match establishes that RTR has the supplied recording. It does not prove the social clip comes from it. Keep that distinction visible in the queue. Likewise, no database hit means “not found using these identifiers,” never “this recording does not exist.”

**Next actions and queue behavior.**

Store lookup outcome separately from the next action. Keep the existing public publication status separate from both. Do not store a second `ingest_needed` boolean that can disagree with the next action.

| Next action | Meaning |
| --- | --- |
| `new` | Imported; lookup has not completed |
| `check_failed` | Lookup failed; retry without asserting absence |
| `conflict` | Supplied evidence or direct identifiers disagree |
| `resolve_needed` | Identity remains uncertain, there are plausible alternatives, or the supplied URL cannot identify one recording |
| `recording_needed` | Research identifies the meeting but supplies no full recording; not a claim that none exists |
| `ingest_needed` | A specifically identified recording has no match under the checked identifiers and no unresolved competing candidate; review before any later ingestion |
| `moment_needed` | A single existing recording is associated; clip/timestamp and editorial claims still need review |

Precedence: query error → contradictory evidence → unresolved identity → missing recording → no archive match → associated recording. The evaluator must exhaust available direct identifiers before classifying missing metadata as a blocker: an exact URL can identify a page despite a blank body or date.

Do not emit `ready`, `ingesting`, or `published` as new pipeline states in Milestone 1. Show an existing entry's `draft/published/hidden` state as a separate badge. A proposed timestamp stays proposed, including when it is numerically in range. Unknown duration means no duration verdict. Transcript absence is a separate capability indicator and does not prevent an exact recording match.

Queue route: `/context/candidates`, gated by the current Clerk editor allowlist. Place the static route before `/context/{entry_ref}` in both services. Show next action, plain-language reason, source post, proposed meeting facts, matched/suggested RTR links, research evidence, existing-entry link, and last checked time. Filter by next action and paginate. Allow recheck of a candidate or a bounded selected batch. Keep the existing editor available for the manual process. No bulk publish or ingest button.

For machine import, use a token-gated Archive candidate endpoint with a distinct importer actor. It may only write research records. Do not invent a Clerk identity. Editor-triggered actions follow the current verified-session → resolver → Archive-token-and-editor-allowlist pattern. A forged user ID in the browser payload grants no access. Queue responses are private/no-store and noindex; candidate records never enter public lists, excerpts, RSS, or sitemaps.

**Agent delivery plan after approval.**

Use a lead and at most three concurrent workers. Assign proficiency to the risk of the work. The tasks below are concrete dispatch briefs; exact model selection can follow the models available at execution time.

First, the lead freezes the schemas, lookup-result contract, state truth table, route names, migration head, and file ownership. Create an integration branch from fresh main and one isolated worktree per agent, with private scratch directories. The lead owns shared main files, model registration, migration ordering, documentation, work-order numbering, integration, and merge decisions. Workers return commits and evidence; they do not push, merge, deploy, or write production data.

| Concurrent worker | Proficiency | Dispatch instructions and completion evidence |
| --- | --- | --- |
| Import and storage | Standard implementation agent | Own `importer.py`, `store.py`, CLI and import tests. Implement the frozen contract and idempotent observation handling. Use only local fixture data/SQLite. Prove repeat import, changed input, two providers citing one post, malformed rows, and concurrent duplicate import. Return counts and tests. Do not change matching, routes, or public entries. |
| Meeting lookup and state | Strong reasoning agent | Own `lookup.py`, `status.py` and their tests. Reuse verified URL/identifier conventions. Prove wrapper alias hits, tenant separation, conflicting RTR/source links, ambiguous metadata, missing metadata, query errors and duplicate records. Show evidence for each verdict. No network resolution, ingestion, metadata repair, or probabilistic auto-match. |
| Private queue | Standard UI agent | Own queue template, script, package route handlers and route tests against the frozen service interface. Reuse editor auth and styling. Render uncertain fields and reasons plainly. Prove pagination, auth rejection, escaped research text, recheck errors and public exclusion. Provide local browser evidence after integration. Do not add publishing or edit shared main files. |

The three packages can proceed concurrently after the contract is fixed. Queue and importer tests initially use the contract with local fakes; they must also pass against the real lookup/storage implementation after integration. The lead reviews schema/model patches before the workers depend on them and alone edits shared service entry points and the migration chain.

In a second wave, a fast agent checks documentation, fixture provenance and the completion funnel. A strong reviewer independently challenges wrong-meeting matches, source-update races, auth, and public leakage. They report findings rather than editing the same files concurrently. The lead resolves findings, runs required checks, verifies the browser workflow, and prepares one reviewable PR. This is a dependency-aware split, not four agents editing `archive/main.py` at once.

Every worker reads `AGENTS.md`, this plan and the relevant handover. Use explicit local `DATABASE_URL` and local `ARCHIVE_BASE_URL`; never inherit production values from a parent `.env`. No YouTube fetching from this Mac. Synthetic tests are allowed only for a clearly identified branch using a schema already demonstrated by real data, and must be labeled as such.

**Acceptance and release.**

Use actual Sheet rows once its link and column mapping are available. Include the already published examples as cross-checks where they occur in the source. Identify expected associations independently before evaluating importer output. Do not claim a real missing-recording or conflict case was tested unless the sample actually contains one.

Required checks:

- Import the same batch twice: second run creates no new candidates or unchanged observations.
- Existing editorial entries remain byte-for-byte unchanged. No meeting ingest, transcription job or public entry is created by import/recheck.
- URL aliases find wrapper recordings; per-tenant IDs do not collide; government/date/body alone never becomes a confirmed association.
- Failed queries remain retryable errors. Ambiguity and contradictory identifiers cannot reach an exact association.
- New research invalidates stale results without losing prior evidence or overwriting existing editorial associations. Conflicting providers cannot silently replace one another. Deleting a linked meeting clears the FK and makes the queue require recheck rather than displaying a stale match.
- Unauthorized visitors cannot read or mutate the queue. Candidates are absent from all public outputs. A candidate matching an existing published post links to it without editing it.
- Local browser verification covers import results, filtered queue, evidence expansion, recheck success/error, and the ordinary Context editor still working.
- Run the current CI gates: Ruff lint and formatting, `python -m pytest`, both migration upgrade/check runs with separate local SQLite databases, backlog TOC/integrity checks, `npm ci`, and `npm test`. Test the new uniqueness/migration behavior on disposable PostgreSQL as well if it uses dialect-dependent upserts.

Report actual counts with two denominators: input rows and unique candidates. Show rows received → valid/rejected → new/updated/unchanged observations → unique candidates by next action. Separately count matched existing recordings and existing editorial entries. Count source rows that collapse to one post rather than losing them from the funnel. Do not describe imported rows as verified moments or newly covered governments.

The change needs one additive Archive migration, with small-table indexes and no meeting/transcript backfill. Ship Archive first, then resolver. Keep candidate availability checks isolated from public pages; an old schema or unavailable candidate service must not break existing Context. Roll back application code while retaining the additive candidate tables if necessary. Merging does not deploy: releases remain manual under this repo's instructions, and the migration runs at deployment.

**Later milestones, not part of this approval.**

Milestone 2 adds an operator-approved bridge to existing ingestion and tracks the returned meeting/job result. It must preserve government ownership checks, video-only ingest rules, and the dedicated YouTube drip restriction. Recording available, transcript pending and transcription failed are distinct outcomes; a video-only page may still be editorially useful.

Milestone 3 validates the proposed moment and prefills the existing editor. Use the transcript and recording first. Support another camera angle, approximate timing and recording cutoff as real outcomes. Keep uncertain allegations attributed to the speaker. Preserve enough evidence to explain the proposed label and the surrounding context. Reuse normal editor save/publish behavior, with no automatic publication. A custom matcher earns a separate proposal only if a measured sample shows that manual/Muse-assisted validation is the bottleneck.

**Source found during implementation.** The connected Drive contains the populated “IG Public Meetings - City, State, Date, Recording” Sheet (`1EdsnR7iE8mLyVV0Cv31LEJNjckeM12FmhYeoC7223fE`, `Sheet1`). Its 16 columns now have an explicit export mapping in `scripts/context_candidate_maps/ig_public_meetings.json`. The source was read only. No Muse API capabilities are assumed. Research claims live in JSON on the candidate and in immutable observations, rather than a separate database column per proposed fact.
