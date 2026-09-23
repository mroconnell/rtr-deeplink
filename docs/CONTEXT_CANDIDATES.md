# Context research queue

WO-1014 implements Milestone 1: import research, check existing recordings, and
show an editor the next action. Publication remains in the existing Context
editor. A meeting match does not verify a proposed timestamp or a speaker's claim.

## Import an export

Export a CSV from the research Sheet, or supply a JSON array of canonical rows
(an object with a `rows` array also works). The populated source reviewed on
September 23, 2026 was [IG Public Meetings - City, State, Date, Recording](https://docs.google.com/spreadsheets/d/1EdsnR7iE8mLyVV0Cv31LEJNjckeM12FmhYeoC7223fE/edit),
tab `Sheet1`. The importer never reads or writes the Sheet itself.

Set `ARCHIVE_BASE_URL` to the intended Archive service and `ARCHIVE_INGEST_TOKEN`
using the existing secure operator environment. Preview is the default:

```bash
python scripts/import_context_candidates.py ./research.csv \
  --provider ig-public-meetings \
  --source-location 'https://docs.google.com/spreadsheets/d/1EdsnR7iE8mLyVV0Cv31LEJNjckeM12FmhYeoC7223fE/edit#gid=0' \
  --map-file scripts/context_candidate_maps/ig_public_meetings.json
```

Review the JSON report. Repeat the command with `--apply` to store the accepted
rows. Each call accepts at most 100 rows; it does not schedule another batch.
The CLI exits nonzero when rows are rejected or fail. An apply can still commit
other valid rows, so use the per-row report before retrying. Replaying the same
export creates no duplicate candidate or observation. Preview writes nothing;
its `new` count means lookup will run on apply, not that a meeting is absent.

The mapping is a JSON object from canonical field to source header. Repeated
`--map 'social_url=Reel URL'` options can override individual mappings. Unmapped
source columns stay in the original observation and do not become lookup facts.
Muse, Sheets, and future sources use the same provider-independent intake.

Canonical input fields are `social_url` (required), `source_record_key`,
`source_label`, `jurisdiction`, `state`, `gov_id`, `meeting_date`, `meeting_body`,
`recording_url`, `rtr_link`, `t_seconds`, `title`, `summary`, `notes`, `evidence`,
`proposed_match`, `source_timestamp`, `source_notes`, and `source_ingest_claim`.
The last four retain source research; an ingest claim never drives pipeline state.
Dates must be exact `YYYY-MM-DD` to become a date claim; other date text stays
unresolved with a warning. Seconds accept an integer or `HH:MM:SS`. Blank facts
stay unknown. Original text is preserved, including editorial text over the
public editor's length limit. The queue displays imported text as escaped data.

Keep the provider name stable across exports. By default the source key is the
canonical social post identity, independent of Sheet row order. If the same
source key has different payloads within one export, all those rows are rejected:
sorting a Sheet cannot establish which research is newer. Review and consolidate
them, or assign distinct stable source keys when they are independent sources.
An existing source key cannot be reassigned to another post. Changed observations
are appended; replaying an older observation does not make it active again.

## Review candidates

Open `/context/candidates` while signed in as an existing Context editor. The
allowlist remains `CONTEXT_EDITOR_CLERK_IDS` on Archive. The queue has 25 rows per
page, a next-action filter, source details, observations, lookup evidence, and
recheck for up to 25 selected candidates. After recheck, use **Refresh queue**.

| Next action | Meaning |
| --- | --- |
| Not checked yet | Lookup is pending, or a formerly matched meeting was deleted |
| Check failed — retry | The query failed; retry, without assuming the meeting is missing |
| Review conflicting evidence | Direct identifiers or meeting claims disagree |
| Identify the meeting | The available evidence cannot identify one recording |
| Find the full recording | No usable full-recording link was supplied |
| Review recording for ingestion | An identifiable recording has no match under the checked identifiers |
| Review the moment and explanation | An existing recording matches; timing and editorial review remain |

Existing Context entries appear separately with their current publication state.
Imports and rechecks never edit them. Titles, summaries, timestamps and match
labels remain research suggestions. Use the ordinary entry editor for editorial
work; automatic editor prefilling is a later milestone.

Lookup reads current slugs, stored URL aliases, normalized source URLs and
fixture-verified platform identifiers. Tenant namespaces are retained. Government and
date can suggest pages but cannot establish an exact match. Body claims help
check contradictions and determine the next action. Unrecognized
URLs and old slugs can require manual research. An unrecorded YouTube mirror of a
known Granicus page also remains unresolved unless Archive holds evidence linking
them. Transcript availability is informational and does not establish a moment.

## Storage, access and release

Archive owns `archive/context/` and two new tables: `context_candidates` and
`context_candidate_observations`. Research and lookup results are separate.
Immutable observations retain their provider and original payload. A newer import
invalidates old lookup results; a version check prevents a stale recheck from
overwriting newer research. PostgreSQL source locks and candidate row locks protect
concurrent imports; SQLite takes its write reservation before reading ownership.

Machine import uses Archive's existing bearer token at
`POST /internal/context/candidates/import`. Editor rechecks use the verified Clerk
session through `/api/context/candidates/recheck`; a browser cannot choose a user
ID. Queue responses are private/no-store and noindex. Candidate rows do not enter
public feeds, search, excerpts or sitemaps. Import performs no remote resolution,
social fetching, ingestion, transcription, or publication.

Deploy Archive first, then resolver. Archive's normal pre-deploy migration adds
the two tables at revision `9f20cd299f30`; it has no meeting backfill. An unavailable
candidate schema fails only the private queue. Roll back application code while
retaining these additive tables if needed. Merging this change does not deploy it.

For local runs, explicitly set both `DATABASE_URL` and `ARCHIVE_BASE_URL` so the
services cannot inherit production values from a parent `.env`.

## Verification

The September 23 local pilot used the actual 31-row export (29 distinct posts).
The empty local Archive makes this a test of intake and repeat imports, not a
measurement of production Archive coverage.

| Result | First apply | Same export again |
| --- | ---: | ---: |
| Input rows | 31 | 31 |
| Accepted rows / unique candidates | 27 / 27 | 27 / 27 |
| Rejected rows | 4 | 4 |
| Created observations | 27 | 0 |
| Unchanged observations | 0 | 27 |
| Failed rows | 0 | 0 |

The four rejected rows are two differing versions each for Dallas and Santa
Clarita. They represent two posts, excluded until their source identity or
research is reconciled. No row order was treated as a version date. The local
queue contained 13 `ingest_needed`, 10 `recording_needed`, and 4 `resolve_needed`
candidates, and zero matched recordings or editorial entries. Those counts are
expected for this deliberately empty local Archive, not claims about RTR live.
Database inspection confirmed zero meetings, public entries and transcription
jobs after both imports.

All 353 Context Python tests and 85 JavaScript tests passed. Tests cover exact
alias matches, tenant separation, conflicting identifiers, query failures,
source updates, stale rechecks, editor authorization, escaped text and public
exclusion. PostgreSQL migration and simultaneous duplicate/retarget imports
passed in a disposable Docker container. Both standard SQLite Alembic checks
passed. PostgreSQL's unfiltered check reports only the four pre-existing,
intentionally unmapped search objects documented in the CI workflow; none belongs
to Context, and no drop operation was accepted.

Chrome browser checks covered the rendered queue, pagination, filtering, original
research, successful batch recheck, an unavailable Archive error, and navigation
to the existing editor. Two localhost services used a disposable authentication
harness; real authorization gates are covered by route tests. OS accessibility
was not enabled. No production data was changed.

See the WO-1014 entry in `BACKLOG_DONE.md` for the full-suite result and the
existing local-export test limitation.
