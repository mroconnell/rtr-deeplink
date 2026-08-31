# Pending measurements

Entries here aren't blocked on engineering, and they aren't a human
action waiting to be taken (that's `BACKLOG.md`'s "Needs a human"
section) — they're blocked on **time or traffic accumulating** before a
report is even worth reading. Filing a "check back in a few weeks" item
in `BACKLOG.md` mixed it in with actionable engineering work and made it
look adjacent to the actionability ordering there, when it isn't
actionable at all until its date arrives.

Each entry names what's being measured, the earliest date it's worth
checking, and the decision the check will resolve. **Once checked, move
the entry into `BACKLOG_DONE.md`** with the decision made (`[Investigated
YYYY-MM-DD]` if no code changes, `[Done YYYY-MM-DD]` if it triggers one) —
same lifecycle as an engineering item moving out of `BACKLOG.md`, just
gated by a date instead of by a fix landing.

This file links back to `BACKLOG.md`/`BACKLOG_DONE.md` for deeper
context; those files generally should **not** link forward to this one —
an item here has already left the active engineering list, and a reader
of `BACKLOG.md` shouldn't need to also track this file to know what's
buildable right now.

## [check no earlier than mid-to-late September 2026] State/hub indexing verdict — did the 2026-08-23 rebuild move the needle?

**What's being measured**: whether the 2026-08-23 `/state/*` and `/j/*`
rebuild changed Google's indexing verdict for those two surfaces.
`STATE_HUB_PAGES.md` is the full reference for how those pages work, why
each design decision was made, what was tried and rejected (with
measurements), a tuning table, and the ranked list of future
improvements — read it before changing anything on these two surfaces
rather than reverse-engineering the reasoning from `crud.py`.
`BACKLOG_DONE.md` keeps the original pre-rebuild investigation.

**How to measure**: pull a Search Console indexing export (login-gated
dashboard) and compare against the **3.6× (`/j/`) and 3.1× (`/state/`)
over-representation figures**, not the raw non-indexed count — the raw
count moves with corpus growth on its own, so it can't answer this
question by itself.

**Earliest check-by date**: at least a few weeks out from the
2026-08-23 rebuild — nothing to do and nothing to change in the code
before then.

**Not part of this**: the still-open engineering residuals the rebuild
left behind are filed separately in `BACKLOG.md` under "Open bugs" and
aren't blocked on this dashboard check.
