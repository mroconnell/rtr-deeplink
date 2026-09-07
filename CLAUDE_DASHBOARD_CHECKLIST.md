# Dashboard checklist — 2026-09-07

Six items, all pulled from `BACKLOG.md`'s "Needs a human" and
"Search Console, structured data & SEO plumbing" sections. Each is a
login-and-look/click task — no code changes, no destructive actions.
Re-verified against `BACKLOG_DONE.md` and recent commits before listing;
none showed clear evidence of already being resolved.

---

## 1. Search Console → Page indexing — click Validate Fix for the reslug redirect

**Step 1 — Search Console → `redtaperecordings.com` property → Page
indexing.** Find the issue covering the old (pre-reslug) permalinks —
these were serving `200` with a different canonical instead of a real
`301` until the 2026-08-31 fix. The underlying bug is fixed and
confirmed live (`curl` against production 2026-08-31 showed real
`301`s, e.g. `/m/meeting` → `/m/tucson-az-2026-08-05-regular-meeting`),
but nobody has clicked Validate Fix yet.

**Step 2 — Click "Validate Fix" on that issue.** Don't expect it to
clear 100% — some of the same category is deliberate canonicalization
behavior (see `BACKLOG.md`'s "Reasons preventing pages from being
indexed" entry, item 6 below), not a bug.

*If this specific issue is no longer listed at all* (already validated
or expired off the report), the item is done — no need to hunt further.

---

## 2. Render → `rtr-deeplink-archive` — confirm WO-80 + FK-cleanup fixes are deployed

Both fixes are confirmed on `main` (re-checked 2026-09-05): `/api/health`
uses `LIMIT 1` not `SELECT count(*)`, and `delete_meeting_pages_by_slug()`
deletes child rows before the page. `autoDeploy: false` means merging
never ships this on its own.

**Step 1 — Render dashboard → `rtr-deeplink-archive` service → Events
(deploy history) tab.** Look for the most recent deploy's build/deploy
timestamp.

**Step 2 — Compare against 2026-08-30 13:28 PDT (= 2026-08-30 20:28
UTC)**, when both fixes landed on `main`. If the latest deploy is
**before** that time, the fixes are still not live — click **Manual
Deploy → Deploy latest commit**. If **after**, nothing to do; the
service is already running the fix.

*Supporting signal (not proof): no further `HTTP health check failed` /
`ForeignKeyViolationError` alerts matching either bug's shape have shown
up in inbox-triage runs since 2026-09-03 — consistent with an
intervening deploy, but not confirmed.*

---

## 3. Render → `rtr-transcription-worker` / `-2` — confirm WO-88 CivicClerk fix is deployed

Fix (`_reconstruct_cdn_stream_url()` in `app/platforms/civicclerk.py:77`)
is confirmed on `main`, but the auto-transcription retry path imports
the platform module **in-process** inside the worker, so a worker still
running a pre-fix build hits the bug regardless of the resolver's own
deploy state. Neither worker service has a schema-info-style endpoint to
check this via API.

**Step 1 — Render dashboard → `rtr-transcription-worker` service →
Events tab**, then repeat for **`rtr-transcription-worker-2`**.

**Step 2 — Compare each service's latest deploy timestamp against
2026-08-31 13:14:37 UTC** (already UTC, no conversion needed) — the
timestamp of transcription job 1308
(`kaysville-ut-2023-04-28-city-council-work-session`), which failed 3/3
with the exact pre-fix symptom. If either worker's latest deploy
predates that time, click **Manual Deploy → Deploy latest commit** on
it.

---

## 4. Render + UptimeRobot → `rtr-deeplink` SIGABRT crash-loop — pull crash logs & memory graph

**This entry in `BACKLOG.md` is stale — worse than what's written
there.** It currently reads "13 times... through 2026-09-05 08:45 UTC."
Today's inbox-triage run (`CLAUDE_INBOX_TRIAGE.md`, 2026-09-07 section)
found the real running total is now **18** crash alerts since
2026-08-30, plus **6** UptimeRobot outages with no matching Render alert
(was 3), plus a brand-new signal: Search Console flagged a **"Server
error (5xx)"** indexing-blocking reason for the first time
(2026-09-06 21:41–21:46 UTC), timed ~1h52m after a 19:54–20:09 UTC
outage — a plausible first sign of external SEO impact from the
crash-loop. None of this has been promoted into `BACKLOG.md` yet (the
promotion rule waits for the entry to age 7 days).

**Step 1 — Render dashboard → `rtr-deeplink` service (`srv-
d9qhdobm8hqs738fgkog`) → Logs, filtered around a crash with no matching
alert** (the two hardest to explain — pick either): **2026-09-06
19:54:35–20:09:51 UTC** or **2026-09-07 04:19:15–04:24:20 UTC**. Look
for the actual abort traceback just before the restart — application
logs so far only show the aftermath (`Unclosed client session` /
`Unexpected error 9 on netlink descriptor`), not the cause.

**Step 2 — Render dashboard → `rtr-deeplink` service → Metrics → Memory.**
Check the memory graph across the same two windows above, and also
around the most recent "Exited with status 134" alert (2026-09-07
01:08:11 UTC) — the working hypothesis is allocator abort under memory
pressure on the `starter` (512MB) plan, same pattern as the 2026-08-25/26
incident that prompted (then reverted) a plan bump to `standard`.

**Step 3 — Search Console → `redtaperecordings.com` property → Page
indexing.** Confirm whether the new "Server error (5xx)" reason is
real and note how many/which pages it names — this can't be checked
without dashboard access (auth-walled), so it's currently unconfirmed.

Whatever you find (crash cause, memory pattern, 5xx page count), it's
worth writing back into `BACKLOG.md`'s SIGABRT entry directly since a
session with Render/GSC access is exactly what's been missing.

---

## 5. GitHub → Security tab — dismiss the Durham secret-scanning false positive

**Step 1 — GitHub → `mroconnell/rtr-deeplink` → Security tab → Secret
scanning alerts.** Find the alert on
`tests/fixtures/civicplus/durham_agendacenter_citycouncil.html:103`
("Google API Key").

**Step 2 — Confirm it's Durham NC's own public `GoogleMapsKey`** (the
alert's own "Public leaks" section already lists the same key in 5
unrelated public repos that scraped the same page — no RTR credential
involved).

**Step 3 — Dismiss with reason "Used in tests."**

---

## 6. Search Console → Page indexing — "Not found (404)" category, check for stale reslugged permalinks

Three of four categories from the original 2026-08-23 alert are
resolved/explained; "Not found (404)" is the one still without a URL
list pulled.

**Step 1 — Search Console → `redtaperecordings.com` property → Page
indexing → "Not found (404)" row.** Open it and pull the URL list.

**Step 2 — Check whether any of the listed URLs are old (pre-reslug)
permalinks** that should now show as a redirect (301) rather than a
404, now that the 2026-08-31 `_SLUG_REDIRECTS` fix is live. If none are,
this category is likely just genuine 404s from de-indexed content
(expected/fine). If some are, that's new information worth adding to
this entry in `BACKLOG.md`.

*Do not touch the other two categories in this same report*
("Alternate page with proper canonical tag" and "Duplicate, Google
chose different canonical than user") — those are deliberate,
documented canonicalization behavior, not bugs.
