"""Meeting Finder (WO-1023/WO-1024): one pipe every government goes
through to find one real meeting with video, or say plainly why not.

See docs/MEETING_FINDER.md for the design. This package holds the
shared data shapes (`models.py`), the one picking rule (`pick.py`),
Resolve (`resolve.py`), the identity check (`identity.py`), and Verdict
(`verdict.py`). `runner.py` wires them together for
`scripts/meeting_finder.py`.

WO-1024 built the core (models, pick, resolve, identity, verdict,
runner, CLI) at entry `resolve` only. WO-1025 owns `fetch.py` (the one
fetch helper for Start/Identify/Scan/Hop). Wave 2 builds List, Identify,
Scan, Hop and Start on top of this.
"""
