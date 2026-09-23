# Dashboard checklist — 2026-09-23

One item today. Everything else in BACKLOG.md's "Needs a human" section
(and the other places this routine checks: Search Console/SEO subsection,
Trust/Roadmap `[HUMAN]` items) needs either a production script run, a
judgment call, or research — not a quick dashboard glance — so it's left
off this list on purpose. See BACKLOG.md for those.

## 1. Render bandwidth cap — size the overage cost

**Issue**: Render alerted twice that the account hit its bandwidth cap
this billing cycle: "Approaching Bandwidth Limit" (>70% of 25 GB) on
2026-09-09 at 12:09 UTC (day 9 of the cycle), then "Reached the
Bandwidth Limit" (100%) on 2026-09-12 at 12:09 UTC (day 12). Both times
are already UTC — no conversion needed. Per the alert text, everything
used past that point bills at $15/100GB until the cycle resets. Nobody
has opened the dashboard yet to see the real dollar exposure or what's
driving it (BACKLOG.md, "Needs a human" → "Production actions only Ryan
should take").

**Not the same problem as before** — the old double-billed-proxy cause
(`ARCHIVE_BASE_URL` routing the public site through the Archive over the
public internet) was fixed 2026-08-30 by moving it to Render's private
network, and an even older version of this same alert type turned out to
have a wrong stated limit (5 GB claimed vs. 25 GB real). Checked both
against BACKLOG_DONE.md and git log 2026-09-23 — no entry closes this
2026-09-13 occurrence, so it's still open.

**Step 1 — Render → Workspace → Billing → Included Usage**
Go to `https://dashboard.render.com/w/tea-d21a0h24d50c739htil0/billing`.
Look for the **Monthly Included Usage** table's Bandwidth row and its
breakdown by category (HTTP Responses, Service-Initiated, WebSocket
Responses, Service-Initiated Private Link — same categories a prior
check used). Note the total GB used and how far past 25 GB it is.
- If usage is still climbing past 25 GB: this is real, ongoing overage
  cost — note the category driving it (HTTP Responses is the likely
  culprit for this app: video/transcript proxying).
- If Private Link bandwidth is 0 MB and HTTP Responses is high: the
  private-networking fix from August is working as intended (that's
  fine) and this is organic public traffic, not a regression — the
  question becomes whether normal traffic has just grown past 25 GB and
  the plan needs a bigger included allowance.

**Step 2 — same page → look for a cost/overage figure**
Look for a billed or projected overage dollar amount for this cycle
(sometimes shown near the usage table, sometimes only inferable from
GB-over-25 × $15/100GB). Write down: GB over cap, and the resulting $.

**What each answer means**: a small overage (a few GB, a few dollars) —
note it and let the cycle reset; no action needed. A large or accelerating
overage — worth deciding whether to upsize the Render plan's included
bandwidth or dig into what's driving the extra traffic. Either way, the
next step is recorded in BACKLOG.md under this entry once the real
numbers are in hand — update that entry with what the dashboard shows.
