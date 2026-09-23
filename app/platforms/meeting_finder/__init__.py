"""Meeting Finder (WO-1023/WO-1025+). See docs/MEETING_FINDER.md.

Minimal package marker only -- WO-1024 (built in parallel) owns the rest
of this package (Start/Identify/List/Scan/Hop/Resolve/Verdict). WO-1025
owns only `fetch.py` and its tests. If WO-1024 lands its own
`__init__.py` first, the conductor reconciles the two; this file adds no
imports of its own so a merge is a no-op either way.
"""
