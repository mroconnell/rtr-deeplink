"""Neutral home for the logic every finder shares (Ryan, 2026-10-06).

Meeting Finder (`app/platforms/meeting_finder/`) is legacy. The parts
other code depends on live here, moved with no behaviour change:

- `models.py`  -- Candidate, FinderInput, ResolveResult, VerdictRow, outcomes
- `pick.py`    -- the one candidate-picking rule
- `resolve.py` -- resolve a candidate list: tier mapping, video gate,
  audio-only check, kept-despite ranks, CalendarPageError follow
- `fetch.py`   -- Fetcher (the fetch ladder) and BudgetExceeded
- `pacing.py`  -- pace_all_requests: pacing, robots check, YouTube
  refusal, request counting

The old `meeting_finder/{resolve,pacing,fetch,models,pick}.py` paths are
shims that alias these modules, so old imports and test patches work.
This package must not import from `meeting_finder`.
"""
