# Dashboard checklist — 2026-09-17

One item today. Everything else currently tagged `[HUMAN]` in `BACKLOG.md`
needs a decision, a shell/API call, or a second machine — not a quick
dashboard look — so it's left off this list on purpose (see "What was
excluded" at the bottom).

## 1. Render bandwidth overage — find out what's driving it

**Step 1 — Render → Billing → Included Usage**
Go to `https://dashboard.render.com/w/tea-d21a0h24d50c739htil0/billing`.
Look for the **Monthly Included Usage** table, specifically the
**Bandwidth** row (25 GB/month included on the Pro plan).

- Two real alerts already fired this cycle: "Approaching Bandwidth
  Limit" (>70%) on **2026-09-09 12:09 UTC** (day 9 of the cycle), then
  "Bandwidth Limit Reached" (100%) on **2026-09-12 12:09 UTC** (day 12).
  Both timestamps are UTC — convert to your local time if you want to
  cross-check against anything else you remember from those days.
- If the bar shows usage still climbing past 100%, every GB past 25 GB
  is now billing at **$15/100GB** until the cycle resets.
- Look for a "by category" or "by service" breakdown on the same page.
  The obvious guess is video/transcript proxying, but that's a guess —
  read what the table actually says before concluding.

**Step 2 — decide if this is new or a repeat**
This is *not* the same cause as the August bandwidth incident — that one
(the whole public site double-proxying through the Archive over the
public internet) was fixed 2026-08-30 by moving traffic to Render's
private network. If the Step 1 breakdown points at something else,
that's a genuinely new driver worth a BACKLOG.md follow-up. If you're
not sure what you're looking at, screenshot the Included Usage table —
that's the detail a later session would need to act on it.

**Optional side-check — Archive health-check blip**
The 2026-09-14 inbox-triage note flagged a one-off Archive "HTTP health
check failed" alert at **2026-09-13 17:59 UTC**, about 30 hours after
the day-12 bandwidth alert. It's logged as an unconfirmed timing
correlation, not a proven cause — no action needed here, just worth
knowing about if the Step 1 breakdown turns out to show something
throttling-shaped.

---

## What was excluded (and why)

- The `[HUMAN]` items under "Production actions only Ryan should take"
  (backfill scripts, page deletes/re-keys, ingest calls) all need a
  shell with production credentials or a judgment call on real content
  — not a dashboard glance. Left for an interactive session or for you
  to run directly.
- The two YouTube-channel-identity items (WO-175 recheck, WO-211 owner
  channels) need someone to actually watch/read a channel and judge
  whether it's the right government — a real judgment call, not a
  lookup.
- The Search Console "Missing field" entry's own next action is a
  `curl` call with a bearer token, not a Search Console dashboard step.
- Note: the routine that generates this checklist normally looks for a
  "Confirmations nobody has actually watched happen" subsection under
  BACKLOG.md's "Needs a human" section — that subsection doesn't exist
  under that name right now (the section's current subsections are
  "Production actions only Ryan should take" and "Decisions about
  already-live content"). Worth fixing the routine's instructions if
  this keeps happening.
