# Dashboard checklist — 2026-09-10 [CLOSED]

Six `[HUMAN]` items were surfaced this morning (see the original PR #840
for the full walkthrough instructions). Ryan worked through all six live
the same day. Results, and where each is now recorded:

1. **Search Console Validate Fix (reslug fix)** — closed, no click
   needed. Neither GSC category on screen ("Page with redirect": 3
   unrelated homepage variants; "Not found (404)": 3 `/j/` hub pages
   that don't match any known reslugged slug) contained the actual
   reslugged pages. See `BACKLOG_DONE.md`'s "Dashboard checklist for
   2026-09-10" entry.
2. **Render → Archive service deploy (WO-80 + FK-cleanup)** — closed,
   Ryan confirmed deployed. `BACKLOG_DONE.md`.
3. **Render → transcription worker deploy (WO-88 CivicClerk fix)** —
   closed, Ryan confirmed deployed on both workers. `BACKLOG_DONE.md`.
4. **`rtr-deeplink` SIGABRT crash-log/memory-graph investigation** —
   *not closed*, but the human/dashboard step is done: memory pressure
   is now ruled out as the driver for the bulk of the 25 occurrences
   (both the 14-day and today's 4-hour memory graphs stay far under the
   2GB ceiling except the already-known 2026-09-01 spike), and PR #795
   is confirmed deployed and working live. Remains open in `BACKLOG.md`
   with these corrected findings — app-level/dashboard investigation is
   exhausted; next step if pursued further is Render support's own
   infra-level crash diagnostics.
5. **GitHub secret-scanning alert dismissal** — closed, dismissed by
   Ryan with reason "Used in tests." `BACKLOG_DONE.md`.
6. **Search Console 404-export re-check (reslug redirect)** — closed,
   confirmed via direct `curl` against all 6 known reslugged old slugs
   (both the 2026-08-28 batch of 5 and the 2026-08-30 Modesto one) — all
   6 correctly 301-redirect to their new slugs. `BACKLOG_DONE.md`.

New finding surfaced along the way, not yet filed as its own entry:
two `/j/` (jurisdiction hub) URLs in today's "Not found (404)" export
look like meeting-title text leaked into a hub slug
(`/j/beaumont-regular-council-meeting-agenda-tuesday`,
`/j/brampton-meeting`) — worth a look next time someone's in
`BACKLOG.md`.

Two small endpoints landed the same session to make future checklist
runs cheaper: `GET /admin/version` (resolver) and `GET /internal/version`
(Archive) report the running instance's `RENDER_GIT_COMMIT`, so
confirming an already-merged fix has deployed no longer needs a Render
login for either `type: web` service (PR #850).

This file will be overwritten by the next weekday run.
