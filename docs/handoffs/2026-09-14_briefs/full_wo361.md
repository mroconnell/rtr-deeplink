# WO-361: find the platform page first — passive pipeline + access ladder on the homepage-only off-mission governments, then the deeper video walk

Read `preamble.md` (all standing rules), `full_wo320_323_passive_neither.md`, `full_wo337_338_addendum.md`, `full_wo341_343_platform_walkers.md`, `full_wo355.md` first. Your WO number is WO-361. Branch `claude/wo361-offmission-find-platform-first`.

## Why (Ryan, 2026-09-13)
WO-355 re-verified 518 non-YouTube off-mission governments and found 62 of 64 "videos" were the homepage's welcome/promo clip: 476 of the 518 rows had only a homepage on file, and `verify_hub()` was pointed at that homepage instead of a meeting listing. Ryan: "we need to find their platform page by doing the passive pipe and ladder access and then we will have videos that might actually be on mission."

## Population
The WO-355 rows whose starting URL was a bare homepage (476; from `research/wo355_verify.csv` / `wo355_population.csv` at rtr-business HEAD — Breadth is committing them), plus WO-355's 109 no-meeting rows if not already in that set. Exclude the 62 promo-only rows only if their homepage yielded a real hub in phase 3 — i.e. do NOT exclude them; the promo verdict was about the homepage, not the government. Largest population first; chunks ≤150.

## Do, per government
1. **Passive pipeline to find the hub**: phase 1 recon on the domain (DNS gate, homepage, robots + sitemaps), phase 2 classification with the measured weights (English + French), phase 3 targeted fetch of the ranked candidates with the one-hop-deeper behaviour, the guessable first-party paths (/agendacenter, /agendas-minutes, /government/agendas-minutes, /Calendar.aspx?EID=…), the evidence checks (name+state, 800-byte floor, catch-all, payment-portal guard). Output: a confirmed meeting hub URL and platform, or "no hub found" with the candidates tried.
2. **Access ladder where the plain fetch fails**: for candidates that answer 403/blocked/empty, climb the ladder from `scripts/wo147_access_ladder_sweep.py` — plain → browser-shaped headers → headless — before declaring no hub; record the rung that worked. govAccess CNAME → `blocked-waf-akamai`, skip. Never solve a human-verification gate.
3. **Only then the video walk**: `verify_hub()` on the confirmed hub with the deeper options (up to 15 listed meetings, up to 3 with video). Never run it on a bare homepage.
4. **Hand-read** every video collected, in order, until one is on-mission (name AND state; county-tenant and namesake traps; promos, ceremonies, recaps, training are not meetings; CITISTAT-style working sessions are). Ingest tier 1 with `gov_id`; queue tier 3 after the owner pin (>90 min queues); tier 2 → lead file; tier 4 → `meeting-without-video`; no hub → the honest reason with the candidates tried.
5. Research rows under §158 with `wo361_jc_applied_gov_ids.txt`; never commit in rtr-business; WO-356/357/358/360 run concurrently — never touch rows that are not yours; wait on the lock. Never fetch YouTube; never download media; foreground runs, per-call timeout < 10 min, per-fetch 20 s / 3 MB; never idle on a monitor; never stop for scope; if budget runs out stop at a chunk boundary with exact counts and a resumable file.

## Report (Ryan's shape)
Purpose reminder; hub-finding table (Count of N: hub found plain / hub found via ladder rung X / no hub, by platform found); tier table on the hubs found; hand-read table (videos read, passed on which attempt, wrong named with why); video split ("captions available, page live now" / "video, no captions, queued"); Kind A; deploy line; rtr-business files; undone; bold takeaway. BACKLOG_DONE entry, methods section as a separate file, five gates, PR(s), merge on green.
