"""Meeting Finder (WO-1023 onward): one pipe every government goes
through to find one real meeting with video, or say plainly why not.

    Start -> Identify -> List / Scan -> Hop -> Resolve -> Verdict

See docs/MEETING_FINDER.md for the design. Every phase is now built and
wired: `start.py` (Start), `identify.py` (Identify), `listing.py`
(List), `scan.py` (Scan), `hop.py` (Hop), `resolve.py` (Resolve),
`identity.py` (the pin/audit identity check), `verdict.py` (the
read-only result row), `fetch.py` (the one fetch ladder Start/Identify/
Scan/Hop all share), `pick.py` (the one candidate-picking rule Resolve
applies), and `models.py` (the shared data shapes). `runner.py` (WO-1030)
is the phase loop that wires all of the above together for every entry
point (`start`/`identify`/`list`/`scan`/`resolve`), driven by
`scripts/meeting_finder.py`.
"""
