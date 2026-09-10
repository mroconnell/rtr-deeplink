# Dashboard Checklist — 2026-09-09

Ready-to-click items from `BACKLOG.md`'s `[HUMAN]` entries, filtered to
"log into a dashboard and look/click" items only. Re-verified against
`BACKLOG_DONE.md`, `CLAUDE_INBOX_TRIAGE.md`, and `git log` before listing
— see notes on each item for what changed since `BACKLOG.md` was last
updated. All times below are given as UTC (as recorded) with Pacific
Daylight Time (UTC-7) in parentheses.

---

## 1. `rtr-deeplink` (main resolver) — crash logs, deploy check, bandwidth (most urgent)

**Step 1 — Render → `rtr-deeplink` → Events/Deploys tab.**
Check the most recent successful deploy's timestamp. If it predates
today, PR #795 (merged to `main` at `93d6365`, fixes a `RuntimeError:
Response content shorter than Content-Length` on `/` and
`/api/health/resolve-check` caused by `handle_head_requests` not
restoring `request.scope["method"]` after a HEAD request) is on `main`
but not live. It's a small, already-merged, already-tested fix — safe to
ship. It's also a plausible (unconfirmed) explanation for some of the
UptimeRobot flapping in Step 2, since it hits exactly those two routes.

**Step 2 — Render → `rtr-deeplink` → Logs/Metrics.**
Pull the real crash traceback and memory graph around these SIGABRT
(status 134) restarts — `BACKLOG.md` still says "13 times," but daily
inbox-triage runs (2026-09-06 through 09-09) put the real count at
**21 since 2026-08-30**, so treat the number in `BACKLOG.md` as stale.
Two windows worth prioritizing since neither has a matching Render alert
to anchor on otherwise:
  - 2026-09-04 22:42 UTC (15:42 PDT) and 23:34 UTC (16:34 PDT)
  - Most recent alert: 2026-09-09 06:34:33 UTC (2026-09-08 23:34:33 PDT)
Also worth a look: UptimeRobot's "no matching Render alert" undercount
jumped from 8 to 16 in the last 24h — a 23-min cluster of 4 outages on
2026-09-08 14:38-15:01 UTC (07:38-08:01 PDT), plus 4 more on 2026-09-09
09:46-12:35 UTC (02:46-05:35 PDT). This recurrence is exactly what a
2026-08-29 standing decision (`BACKLOG_DONE.md`, "Four Render-dashboard
`[HUMAN]` items walked through live with Ryan") flagged as "worth
revisiting if it recurs post-WO-80" — it has, sharply.

**Step 3 — Render → Workspace → Billing → Monthly Included Usage**
(https://dashboard.render.com/w/tea-d21a0h24d50c739htil0/billing).
*Not yet in `BACKLOG.md` — surfaced by today's automated inbox-triage
run, flagging it here since you'll already be in the dashboard.* First-
ever "Approaching Bandwidth Limit" alert fired 2026-09-09 12:09 UTC
(05:09 PDT): >70% of the 25 GB/month Pro-plan allowance used by day 9 of
the cycle. Note: a near-identical alert on 2026-08-22 turned out to be a
false alarm once checked live (real limit was 25 GB not the 5 GB the
alert implied, and usage was safely on pace) — so don't panic on the
alert text alone, but 70%+ by day 9 is a much faster pace than that
prior 58%-by-day-22 reading, so it's worth actually looking at the trend
and which service is driving it this time.

---

## 2. Archive service — confirm two merged fixes are actually deployed

**Step — Render → `rtr-deeplink-archive` → Events/Deploys tab.**
Check the most recent deploy timestamp. If it's before **2026-08-30
13:28 PDT (20:28 UTC)**, two already-merged fixes are sitting undeployed:
`/api/health` uses `LIMIT 1` not `SELECT count(*)` (WO-80), and
`delete_meeting_pages_by_slug()` cleans up `SocialPost`/
`MeetingPageThumbnail` rows before deleting the page (PR #577). No code
change needed — click "Manual Deploy" → "Deploy latest commit" to ship
what's already on `main`. If the deploy is after that timestamp, both
are already live — nothing to do.

---

## 3. Transcription workers — confirm CivicClerk fix reached them

**Step — Render → `rtr-transcription-worker` AND `rtr-transcription-worker-2` → Events tab (check both — they're separate services).**
If the most recent deploy on either predates **2026-08-31 13:14 UTC
(06:14 PDT)**, WO-88's CivicClerk relative-path fix
(`app/platforms/civicclerk.py`'s `_reconstruct_cdn_stream_url()`) hasn't
reached that worker — it calls the platform module in-process rather
than through the resolver's own deployed API, so the resolver's deploy
state doesn't cover it. Redeploy whichever is stale; when redeploying,
don't touch `AUTO_TRANSCRIPTION_REQUESTER_EMAIL` (the one env var meant
to differ between the two). No code change needed. Job 1308
(`kaysville-ut-2023-04-28-city-council-work-session`) is the known
stuck job to retry once confirmed fixed.

---

## 4. Search Console — reslug redirects + a new "Server error (5xx)" flag

**Step — Search Console → redtaperecordings.com property → Indexing → Pages.**
Two things to check in the same report:
- **"Not found (404)" row**: look for these 5 old paths —
  `/m/meeting`, `/m/meeting-1e9bac`, `/m/meeting-38ca49`,
  `/m/meeting-ef5ba6`, `/m/welcome-to-clerkbase`. These now 301-redirect
  to real content (fix live since 2026-08-31, confirmed deployed). If
  still listed, click **Validate Fix**. Don't expect 100% clearance —
  some 404s in this category are real/expected, per the existing
  `BACKLOG_DONE.md` writeup.
- **"Server error (5xx)" row** *(not yet in `BACKLOG.md` — new
  2026-09-06, surfaced by inbox-triage, same dashboard so worth checking
  now)*: open it and note which/how many URLs are affected — this
  dashboard is the only way to get that list. Worth a mental
  cross-reference against Item 1's crash/outage timestamps above; timing
  is suggestive but unconfirmed.

---

## 5. GitHub — dismiss a confirmed false-positive secret-scanning alert

**Step — github.com/mroconnell/rtr-deeplink → Security → Secret scanning alerts.**
Find the alert on `tests/fixtures/civicplus/durham_agendacenter_citycouncil.html:103`
(flagged as a Google API Key). Confirmed false positive: it's Durham
NC's own public `GoogleMapsKey`, embedded in a real fixture of Durham's
live CivicPlus page — already public in 5 other repos that scraped the
same page before this one captured it. Dismiss with reason **"Used in
tests."** Nothing to rotate.

---

*All 5 items re-checked as still open as of 2026-09-09 (no evidence of
resolution found in `BACKLOG_DONE.md`, `CLAUDE_INBOX_TRIAGE.md`, or
recent commits). Item 1's crash count and bandwidth note are updates on
top of `BACKLOG.md`'s existing entry, not new backlog items — worth
folding back into `BACKLOG.md` next time someone's there.*
