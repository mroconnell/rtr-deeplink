# Sweep reports handoff, 2026-09-20

These four CSVs are the real, row-by-row results from three sweeps a
remote session ran on 2026-09-19/20, using tools already merged into
`main` (`scripts/wo905_agendacenter_hop_sweep.py`,
`scripts/wo908_headless_pilot.py`). Only summary counts made it into
`BACKLOG.md`/`BACKLOG_DONE.md` at the time (grep those files for
"WO-908", "WO-909", and "WO-910" for the full narrative) — these files
are the underlying data, and they didn't exist anywhere durable until
this commit. The remote session that produced them runs in an ephemeral
sandbox with no access to `rtr-business`, so it could not put them in
their real home itself.

**This directory is a temporary handoff container, not their final
home.** Whoever picks this up next (a local session with `rtr-business`
access) should move them there following whatever naming/documentation
convention this repo's other WO report CSVs already use in that
directory, then delete this directory from `rtr-deeplink` once they're
safely relocated — these don't need to live in this repo long-term, the
same way no other WO's own report CSV does.

## What each file is

- **`agendacenter_sweep_primary_656govs.csv`** — 656 governments whose
  recorded meeting hub is a bare, empty `/AgendaCenter`-shaped page,
  swept for real video one hop deeper. 111 found a platform link. This
  is a similar, smaller, independently-derived population, not the
  ~1,125-row population `BACKLOG.md`'s "AgendaCenter-empty-shell
  population" entry names from `jurisdiction_coverage.csv` — that list
  still hasn't been run.
- **`agendacenter_sweep_broader_129govs.csv`** — 129 governments with
  some other kind of bare/generic hub (CivicWeb, eScribe, filepro, etc.)
  — a deliberate test of the same tool outside what it was built for.
  38 found a platform link, a higher rate than the primary population.
- **`headless_pilot_1_of_2_WO908_200govs.csv`** / **`headless_pilot_2_of_2_WO909_200govs.csv`**
  — two independent 200-government samples testing whether a full
  headless-browser recheck finds more video than a plain fetch on small
  governments. Both pilots hit a real, different sandbox-only problem
  before finishing (documented in `BACKLOG_DONE.md`'s WO-908/WO-909
  entries) — the real answer to that question is still open and needs
  to run from an environment without those problems.

## Columns

The two AgendaCenter files share one schema: `gov_id,name,state,
population,domain,hub_url,hub_fetch_status,home_fetch_status,
hop_candidates_checked,fetches_used,outcome,platform,hit_url,hit_source,
needs_listing_discovery,all_platforms_found,note,error`.

The two headless-pilot files share another: `gov_id,name,state,country,
gov_kind,population,domain,reject_reason,access_mode,rung_answered,
bucket,platform,hit_url,final_url,waf_family,note,elapsed_seconds,
exception,final_url_is_youtube,direct_file_plausible`.

**`gov_id` in all four files uses this remote session's own internal
encoding from the live Gov Coverage dashboard export it was built
from — it does NOT match `jurisdiction_coverage.csv`'s `gov_id` format
(`us:place:...`, `us:county:...`, etc.).** Match rows to that file by
`domain` instead, not `gov_id`.

## A caution already confirmed on this data

A hand-check of a sample from each file found a real, non-trivial
wrong-government rate among `outcome`/`bucket` rows that show a platform
found — roughly 1 in 5 to 1 in 3, depending on the file (state agencies,
neighboring jurisdictions, decorative videos, website-vendor badge
links). Don't treat a `platform_found`/`platform found via X` row as a
confirmed real meeting without a look — see `BACKLOG.md`'s
"`find_platform_link()` accepts the first vendor-shaped link..." entry
for the standing, already-open bug this traces back to.
