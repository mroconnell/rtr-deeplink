# WO-355: the non-YouTube off-mission governments, re-verified hub → tier with a deeper walk and a deeper hand-read

Read `preamble.md`, `full_wo337_338_addendum.md`, `full_wo341_343_platform_walkers.md` first. Your WO number is WO-355. Branch `claude/wo355-offmission-nonyoutube-reverify`.

## Why
787 governments carry `off-mission` in the research file. Ryan's rule: a turned-away video is a verdict on that video, not the government. WO-340's probe-hook pilot could not find the right listing when the platform label was wrong (12 of 50 rows were really YouTube-sourced) and tested only 38 rows, finding nothing. The 269 YouTube-sourced rows are on the drip lane (WO-353). This WO takes the remaining ~518 whose video lives on a platform the walkers can read, through the programmatic path that produced this weekend's pages.

## Ryan's two rule changes for this run (2026-09-13) — implement them in `verify_hub()` as options, default-on here
1. **Walk deeper.** From the hub, read up to 15 listed meetings (newest first) and collect up to 3 that carry video, instead of stopping at the newest one. Return all three with titles, dates, durations where known.
2. **Hand-read deeper.** Check the collected videos in order until one looks on-mission (a governing body of THIS government, by name and state, a real meeting not a promo/recap/ceremony/training; CITISTAT-style mayoral working sessions count; speeches at chamber events do not). Stop at the first that passes; if none of the three passes, the verdict for the government is `off-mission` again with the three titles recorded, or tier 4 if the listing had no video at all.
Add tests for both (fixtures from real listings: a tenant where the newest meeting is a promo and the second is a council meeting).

## Steps
1. Population: the off-mission rows minus those in `research/wo353_offmission_youtube_recheck.csv` (YouTube-sourced) → ~518. Table by platform and population band; largest first; resumable chunks ≤150 per call.
2. Hub page: the row's hub_url / example_agenda_or_calendar_url / example_meeting_url on the platform's host; if the only address is the homepage, run phases 1–3 (with the one-hop-deeper behaviour) to find it.
3. `verify_hub()` with the deeper walk; the CivicClerk county-tenant and eScribe namesake cautions apply; never fetch YouTube (an embed is tier 2, a lead).
4. Tier per government; hand-read per rule 2 above, one line per video read.
5. Act: tier 1 → page with `gov_id`; tier 3 → owner pin, then queue via `finish_candidate()` (prefer 9–40 min among the passing videos; queue a long one rather than defer); tier 2 → lead file; tier 4 / no meeting / still off-mission → research row updated (line-based, §158, `wo355_jc_applied_gov_ids.txt`; `meeting-without-video-unverified` replaceable; never commit in rtr-business; never download media). Foreground runs, per-call timeout < 10 min, per-fetch 20 s / 3 MB; never idle on a monitor; never stop for scope; if budget runs out stop at a chunk boundary with exact counts and a resumable file.
6. Docs: BACKLOG_DONE entry, methods section as a separate file, five gates, PRs (the verifier change first, as its own PR), merge on green.

## Report (Ryan's shape)
Purpose reminder; population table; tier table (Count of ~518: tier 1 / 2 / 3 / 4 / no meeting / still off-mission / error); hand-read table (videos read, passed on which attempt: 1st/2nd/3rd, wrong named with why); video split ("captions available, page live now" / "video, no captions, queued"); Kind A; deploy line (verifier change + pins + queue lines → resolver deploy); rtr-business files; undone; bold takeaway.
