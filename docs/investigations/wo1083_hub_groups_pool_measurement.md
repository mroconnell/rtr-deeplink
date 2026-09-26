# WO-1083: measuring the hub-groups cache against a starved connection pool

Written 2026-09-26. Read this alongside `BACKLOG_DONE.md`'s WO-1083 entry
and `archive/db/hub_groups_cache.py`'s own docstring, which explain WHAT
was built and WHY. This file is the measurement: what was run, and the
real numbers it produced.

## Why a local measurement, not just "it should help"

The incident this fixes was a real connection-pool exhaustion in
production (2026-09-26, 6:56-7:02 AM PDT): a crawler burst against
`/j/<slug>` ran `crud._hub_groups()`'s uncached GROUP BY dozens of times a
second, held every one of the pool's 5+2 connections per worker, and took
every other route down with `sqlalchemy.exc.TimeoutError`. "Adding a
cache" is not automatically a fix for that specific failure mode --
a plain TTL cache does nothing for the FIRST burst before anything is
cached, which is exactly when a real crawler burst starts. What actually
stops it is the single-flight behaviour (concurrent misses share one
query). This measurement checks that claim against a starved pool
directly, rather than trusting it by construction.

## Method

A local SQLite Archive, seeded with 800 synthetic governments and
4,000-5,500 meeting pages (comparable in scale to the "5,053-page export"
`_hub_groups()`'s own docstring already measures against) -- one
`meeting_pages` row per meeting, shaped to pass `_hub_base_conditions()`
the same way a real ingested page does (video_url set, `agenda_items`/
`video_warnings` explicitly `[]`, matching what `_find_or_create_page()`
always writes -- a first attempt at this script left those two columns
`NULL` and every seeded row silently failed `_is_empty_page_condition()`'s
three-valued SQL logic as a result; worth knowing if this script is ever
adapted, since that failure mode gives an empty result set with no error).

A second, separate SQLAlchemy engine against the same SQLite file, with
`pool_size=2, max_overflow=0, pool_timeout=1.0` -- deliberately smaller
than production's 5+2/30s, so contention shows up over 100 requests
without a multi-minute run. Confirmed live that `aiosqlite`'s async
engine uses `AsyncAdaptedQueuePool` and honors these settings exactly the
way `asyncpg`'s does in production -- the same `QueuePool limit ...
timeout` error class reproduces locally with no Postgres needed.

A local SQLite query against a few thousand in-memory-cached rows takes
microseconds, nothing like the real, over-the-network Postgres round trip
this query takes in production (the actual mechanism behind the
incident). To make a 2-connection pool meaningfully contended locally,
`AsyncSession.execute` was patched for the duration of the benchmark to
force its connection checkout immediately, then hold it for 100ms before
running the real query -- a stand-in for realistic production query
latency, applied identically to both runs below.

100 concurrent simulated `/j/{slug}` requests, each opening its own
session and calling `crud._hub_groups()` directly (not the full
`get_jurisdiction_hub_data()` HTTP path, which also runs several other,
not-yet-cached queries -- the meeting list, highlights, thumbnails, Full
Context entries -- that would swamp the signal under the same artificial
per-query latency and aren't what this WO changes). This isolates exactly
the mechanism the incident named: one whole-table GROUP BY, run with no
cache, on every hub-page request.

Run twice: once with the cache module's single-flight logic replaced by
the old, literal pre-fix behaviour (every call runs its own query, no
sharing), and once with the real fix in place.

## Result

100 concurrent requests, 2-connection pool, `pool_timeout=1.0s`, 100ms
simulated query latency:

| Check | Before (no cache) | After (cache + single-flight) |
| --- | --- | --- |
| Requests that hit a pool timeout | 74 of 100 | 0 of 100 |
| Requests that succeeded | 26 of 100 | 100 of 100 |
| Real GROUP BY queries actually run | 100 | 1 |
| Total wall time for all 100 requests | 2.21s | 0.12s |

Deterministic across repeated runs (fixed random seeds for both the seed
data and the request targets) -- rerun twice, both figures identical to
the ones above.

## Caveats on the numbers

- The 100ms simulated latency and the 1-second pool timeout are chosen to
  make contention visible in a fast local run, not measured from
  production. Production's real numbers (actual Postgres round-trip time,
  30-second pool timeout, 5+2 connections, "dozens of requests per
  second" sustained for ~6 minutes) are different in every dimension --
  this measurement demonstrates the MECHANISM (single-flight collapses
  fan-out into one query and removes contention), not a prediction of
  exactly how close production came to failing at some other load level.
- "Requests that succeeded" undercounts what production would show, since
  every one of the "before" run's surviving 26 requests is racing 99
  others for 2 connections purely due to this test's harness, not due to
  the real page-rendering work an actual `/j/` request also does.

## Reproducing this

The script lives in this session's scratch directory (per this repo's
"subagents share scratchpad" convention, not committed to the repo) --
`wo1083/bench.py`, self-contained, no fixtures beyond
`archive.db.models`. Run from the repo root with:

```bash
DATABASE_URL="sqlite+aiosqlite:///./unused.db" \
  python wo1083/bench.py
```

It seeds `./wo1083_bench.db`, runs both scenarios, prints the table above,
and deletes its own database file when done. A future session that wants
to re-run this (e.g. after further changes to `_hub_groups()`) should
recreate it from the description in this file's "Method" section above
rather than assuming the exact script still exists somewhere -- it was
never meant to be a permanent fixture, only this measurement's evidence.
