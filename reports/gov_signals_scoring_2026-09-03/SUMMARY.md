## Phase 2d — signal scoring

*Run 2026-09-03. `scripts/score_gov_signals.py`; raw sheets in `reports/gov_signals_scoring_2026-09-03/`.*

### Corpus

- **604** target pages (`unresolved`/`unverified`, live count re-derived at run time, not assumed from an earlier document).
- **300** `registry`-tier control pages (random sample).
- **589/604** target pages' real source HTML fetched successfully (the rest: fetch failure or an explicit human-verification gate, skipped per CLAUDE.md's 'politely' rule, never defeated).

### Recovery

- **102** of 604 target pages recovered a `registry`/`pinned` `gov_id` from signals alone.

By platform:

| platform | recovered |
| --- | --- |
| youtube | 42 |
| granicus | 26 |
| escribe | 15 |
| swagit | 10 |
| iqm2 | 7 |
| civicclerk | 2 |

By country:

| country | recovered |
| --- | --- |
| us | 88 |
| ca | 14 |

**Canada, by province** (the number Ryan needs to decide on the BC/QC/NU division-table rows -- ~130 rows, no live-confirmed positive case yet, per CLAUDE.md):

| province | recovered |
| --- | --- |
| ON | 8 |
| BC | 4 |
| AB | 2 |

### Postal-code signal hit rate

- **8** of **75** fetched Canadian target pages (`.ca`/`escribemeetings.com` tenant hosts) carried a usable postal code (11%). Prior calibration (a different corpus -- tenant LANDING pages, not meeting pages) found roughly 1 in 4; this run measures on meeting pages specifically, which is expected to differ and is stated here rather than assumed to match.

### Control regressions

**0 control-tier pages changed `gov_id`.** Target met.

### Per-signal contribution (sequential)

A signal earning zero unique recoveries once the others have already run is dropped, not shipped -- same discipline as the tournament sections above.

| signal | unique recoveries |
| --- | --- |
| org_names | 71 |
| zip_codes | 23 |
| postal_codes | 8 |

