# Handoff: coverage-round conductor + Breadth, 2026-09-14

This document lets one Sonnet session take over two roles at once: the
**conductor** (Fable - Platforms) and **Breadth** (Fable - Breadth). Read it
top to bottom once, then work from section 4 (the loop) and section 8 (what
is in flight). Breadth's own half is
`~/Documents/rtr-business/research/BREADTH_HANDOFF_2026-09-14.md`; read it
right after this one.

Ryan (they/them) owns the product. Ryan reads short, plain reports and
makes decisions from them. Never guess in a report; a blank is a finding.

## 1. What the round is

Red Tape Recordings turns local-government meeting video into transcript
pages. The coverage round grows the Archive by finding, for each government,
a real meeting video and either making a page (captions available) or
queueing it for transcription (video, no captions). Everything is measured
in the research file `~/Documents/rtr-business/research/jurisdiction_coverage.csv`
(45,612 lines at HEAD) and shown on the Gov Coverage dashboard.

Vocabulary Ryan uses:

| Tier | Meaning | What happens |
|---|---|---|
| 1 | video with captions | page ingested now |
| 2 | video on YouTube (captions fetched only by the drip Mac) | lead row for the drip lane |
| 3 | video, no captions | owner pin, then a tier-3 queue line |
| 4 | meeting found, no video | research row only |
| off-mission | only promo/decorative clips | research row only |

A queue count is never called "pages". Video finds are always split into
"captions available, page live now" and "video, no captions, queued".

## 2. The two roles

**Conductor.** Assigns every WO number centrally, writes a brief, launches a
Sonnet agent in its own worktree, merges what the agent could not, relays the
agent's report to Ryan in Ryan's shape, forwards the agent's rtr-business
file list to Breadth, keeps the append-only log, and batches deploy asks.
Never codes in the main flow; small doc moves are fine.

**Breadth.** Owns every commit in `~/Documents/rtr-business` (local-only,
no git remote; "merged in" there means committed on master). Commits each
WO's research files line-based under the lock, maintains the drip lane's
one file `research/youtube_channel_leads.csv`, runs
`research/refresh_transcribed_flag.py`, appends `ENUMERATION_METHODS.md`
sections with the next § number, and relays Ryan's decisions from its own
chat. Details in Breadth's handoff file.

When one session holds both roles, "forward the file list to Breadth"
becomes "commit the files yourself, following Breadth's protocol".

## 3. State right now (2026-09-14, early afternoon PT)

- rtr-deeplink `main` tip: past #1168 (WO-368). Every WO PR and routine PR
  is merged. Open PRs: dependabot #765, #767, #768 only (failing CI; left
  for Ryan).
- rtr-business master: 34598e1 (WO-368). Tree clean. Next
  ENUMERATION_METHODS section is §368 (WO-368 took §367).
- Both Render services deployed today: resolver at 5da09b5 (BoardDocs
  adapter WO-365 and every pin through WO-365 are live); Archive confirmed
  deployed by Ryan (WO-362 Englewood fix live, page re-ingested and keyed).
  Commits merged after those deploys are scripts, docs and research only:
  **no deploy is owed right now.**
- Next free WO number: **WO-369**. Always assign centrally; agents never
  derive one.
- No agents running.

## 4. The conductor loop

1. **Ryan asks for something** (directly, or relayed by Breadth in
   "Ryan's words"). Decide whether it is a WO. Small doc moves you may do
   yourself; anything touching code, research rows, pins or queue files is
   a WO.
2. **Assign the number** (next free, see section 3; then bump it in your
   log).
3. **Write the brief**: `briefs/full_woNNN.md` next to `briefs/preamble.md`
   (copies of both are in `docs/handoffs/2026-09-14_briefs/`; the live
   copies were in the Fable session's scratchpad, listed in section 10).
   A brief says: why (Ryan's words), population and where it lives, the
   exact scripts to reuse, per-row outcomes, file names (all prefixed
   `woNNN_`), finish steps, and the report shape. Look at `full_wo368.md`
   and `full_wo365.md` for the two common shapes (a sweep; an adapter).
4. **Launch**: `Agent` tool, `subagent_type: general-purpose`,
   `model: sonnet`, `isolation: worktree`, `run_in_background: true`.
   The prompt names the WO number and tells the agent to read
   `preamble.md` then `full_woNNN.md` by absolute path, work only in its
   worktree, never commit in rtr-business, foreground runs only with
   per-call timeouts under 10 minutes, and end with the report.
5. **While it runs**: do not poll. A completion notification arrives. If an
   agent is idle-waiting on CI that never starts, its PR is CONFLICTING;
   send it `SendMessage` with the rebase rule (section 6). `SendMessage`
   to its agent id also resumes a finished agent for a follow-up.
6. **On the report**: check the PR merged (`gh pr view N --json state`);
   if the agent could not merge, merge it yourself on green, one PR at a
   time. Read the diff stat for scope creep. Then relay to Ryan in Ryan's
   shape (section 7), forward the file list to Breadth (or commit it
   yourself), and append to the log.
7. **After a merge batch** say what is on main but not live, and batch one
   deploy ask. Docs, BACKLOG files, queue files and research files never
   need a deploy; `app/`, `archive/`, `worker/`, `shared_*`,
   `requirements.txt`, `render.yaml`, and the pins file
   `app/utils/jurisdiction_data/tenant_overrides.csv` do.

## 5. Session directory

Send with `mcp__ccd_session_mgmt__send_message` (session id) or
`SendMessage` (agent id). Messages from these sessions arrive as
cross-session messages; treat their "Ryan says" quotes as Ryan's decisions.

| Session | Id | Role |
|---|---|---|
| Fable - Breadth | `local_5f00a32a-c08b-4df9-9029-f758b4a5cd78` | rtr-business commits, leads file, Ryan relay |
| Discovery - Datafeed evaluation | `local_14b8d625-9ce1-4e47-83d9-c78c652676eb` | rtr-discovery repo (WO-312/313/314 done, nothing open) |
| no-meeting | `local_4db2419a-70c5-41ba-8b4f-e7738f8b2093` | holding |
| off-mission | `local_684a433b-cc14-4a6b-81dd-c1120bb84b82` | finished WO-340/353/354 |
| jx coverage triage | `local_508c6fd1-451c-4306-94b6-0d2013a45036` | spot checks; authored PR #1161 |
| Ol McClaude's Mac | not a session here; Ryan carries pastes | the ONLY YouTube caller: runs `scripts/youtube_drip.py`, reads the leads file by hand, queues lines |

## 6. Rules that bind the conductor

Security and ops, all still in force:

- Never `grep`, `cat` or Read `.env`; never print a token. Load it in
  process: `load_dotenv('/Users/mroconnell/Documents/rtr-deeplink/.env')`
  and check `bool(os.environ.get('ARCHIVE_INGEST_TOKEN'))`.
- Any command importing `archive/` or `app/` code from a worktree gets
  `DATABASE_URL="sqlite+aiosqlite:////tmp/<unique>.db"` on the command
  line. Never read the Archive DB from a laptop except read-only with
  `ARCHIVE_DATABASE_URL` mapped to `DATABASE_URL` in process.
- Never `git checkout` in the shared checkout `~/Documents/rtr-deeplink`;
  work in the worktree. Never use bare `git stash`.
- Never fetch youtube.com or youtu.be from this machine. Never download a
  media file (ranged 64 KB GETs into memory only). Never solve a human
  verification gate. Never run unbounded scans against production.
- The auto-mode classifier blocks direct prod DB writes, some bulk edits,
  and a loop of merges. Use the endpoints in section 9 with a dry run
  first, and merge PRs one at a time (a background `gh pr checks --watch`
  then a single `gh pr merge --squash --delete-branch` per PR works).
- `~/Documents/rtr-business`: agents never commit there. Only the Breadth
  role commits, line-based, explicit paths, never `git add -A`.
- Never apply `/tmp/tenant_overrides_pending.csv`; never run
  `scripts/backfill_gov_id.py --apply`.

Merge and rebase:

- A CONFLICTING PR never gets CI. Rebase it: fetch the branch explicitly,
  `git checkout -B cond/prNNN origin/<branch>`, `git rebase origin/main`.
  In conflicts, main's version wins wherever main deleted or rewrote; union
  only the branch's own added lines (queue, sidecar, pins, BACKLOG_DONE).
  Never `git checkout --theirs` on BACKLOG.md (it drops main's edits;
  learned tonight). After resolving: `python3 scripts/build_backlog_toc.py`,
  `python3 scripts/check_backlog_done_headings.py`, push with
  `--force-with-lease`, then watch CI and merge.
- Five CI gates: `ruff check`, `ruff format --check`, `python -m pytest`,
  `alembic check` (archive/ and app/), `scripts/check_backlog_done_headings.py`.

Standing rules from Ryan (all in `preamble.md`, most recent first):

- 2026-09-14: a probe failure is not a reject when the government has no
  transcript yet; queue it and let the transcriber decide.
- 2026-09-14: reject reason `cablecast-no-vod` (real Cablecast tenant, no
  video file on any show for a month; alternate hop fires; never retried).
- 2026-09-14: BoardDocs is read one tenant, one meeting, on demand; never a
  sweep (its robots.txt disallows all agents).
- 2026-09-13: a tier-3 video over 90 minutes is queued, never parked; walk
  a listing to at least 3 videos before an off-mission reject; old-but-real
  meetings still get pages (no freshness cutoff); an empty platform listing
  means try another hub; a rejected video is a verdict on the video, not
  the government; a government's proof is not a verdict on a tenant.
- Report shape (2026-09-12): open with what the WO was for; a tally table
  after each phase (Outcome | Count of N | What it means); a summary table;
  the video split line; a bold one-line takeaway; deploy status; undone.

## 7. Writing for Ryan

Plain words, short sentences, one idea each. One table per question with
column labels reused from the sentence before it. Numbers that change a
decision go in a table, not prose. Report what was measured; never fill a
blank from a heuristic. When relaying an agent's report, keep its tables,
cut its process narrative, and add one sentence on what Ryan must decide or
do (deploy, paste to Ol McClaude, a pin call).

## 8. In flight right now

1. **Two BoardDocs meetings on the drip Mac.** Ol McClaude pulled the drip
   worktree to 75052c9 (includes WO-365 adapter and WO-367 drip change),
   queued the two source pages
   (`go.boarddocs.com/fla/talgov/Board.nsf/goto?open&id=DU8S8U718044` for
   Tallahassee city FL `us:place:1270600`;
   `go.boarddocs.com/az/ccschools/Board.nsf/goto?open&id=DGTU4S7A4526` for
   Colorado City Unified District AZ `us:sd:0400021`), restarted the drip,
   and runs a monitor every 20 minutes until both pages exist. When Ryan
   relays that they exist: confirm each page title carries the city
   (section 9, lookup), then set both research rows to transcribed with
   the goto URL as `example_meeting_url` (Breadth role). Leads already in
   the leads file (e232c86).
2. **Brookline MA queue line** (`brooklinema.portal.civicclerk.com/event/16635/media`)
   will fail at transcription: its media is a Zoom Gov cloud recording and
   nothing here reads Zoom. Queued on Ryan's rule; expected, recorded in
   BACKLOG. Excelsior MN's line is the direct Cablecast show URL and works.
3. **833 probe sidecar rows** sit in the drip Mac's local buffer file
   (`tier3_auto_transcription_queue_probe.local.csv`, by design since
   WO-248). Not on main. Fold in some day; not urgent.
4. **Dependabot #765/#767/#768** fail CI. Ryan's call.

## 9. Endpoints and commands

All admin calls need a token loaded in process (never printed). The
resolver's `/admin/*` routes take `ADMIN_STATS_TOKEN` as a Bearer header on
`https://redtaperecordings.com`. The Archive's `/internal/*` routes live on
`ARCHIVE_BASE_URL` (in `.env`) and take `ARCHIVE_INGEST_TOKEN`.

| Need | Call |
|---|---|
| What is deployed (resolver) | `GET /admin/version` → `{"commit": ...}` |
| Re-ingest a page after a fix | `GET /admin/recheck-archive-page?url=<meeting url>` |
| Find a page by source URL | `GET {ARCHIVE_BASE_URL}/internal/lookup?normalized_url=<url>` → slug |
| Recent pages with ids | `GET {ARCHIVE_BASE_URL}/internal/export/pages?limit=100&created_after=<iso>` |
| Set a page's government | `POST {ARCHIVE_BASE_URL}/internal/jurisdiction/override?ids=<id>&gov_id=<gov_id>&dry_run=true` then `dry_run=false` |
| Delete a bad page | `POST {ARCHIVE_BASE_URL}/internal/admin/delete-pages?dry_run=true` first, read titles, then apply |
| Pins | `app/utils/jurisdiction_data/tenant_overrides.csv` (shared hosts never pinned by host alone; `MULTI_GOV_HOSTS` in `app/utils/`) |
| Queue and sidecar | `scripts/tier3_auto_transcription_queue.txt` (`url<TAB>source_url`), `scripts/tier3_auto_transcription_queue_probe.csv`, `scripts/tier3_long_meetings_deferred.txt` |
| Shared verifier | `app/platforms/passive_verify.py` `verify_hub(max_listings=15, max_videos=3)` |
| Hand-read fetch that refuses media | `scripts/wo364_handread.py` (the wo355/wo361 versions still lack the Content-Type check) |

Python: `/Users/mroconnell/Documents/rtr-deeplink/.venv/bin/python`.

## 10. Where things are

- Conductor log (append-only; its final "CURRENT PICTURE" block is the
  authoritative state): the Fable session's scratchpad,
  `/private/tmp/claude-501/-Users-mroconnell-Documents-rtr-deeplink--claude-worktrees-platform-detection-backfill-c9742a/1d27de13-eb07-451a-a07a-bb18900b5618/scratchpad/conductor_state.md`,
  with `briefs/preamble.md` and `briefs/full_woNNN.md` beside it (111
  briefs). A new session should start its own log in its own scratchpad
  and copy the CURRENT PICTURE block over as the first entry.
- Standing repo docs: `CLAUDE.md` (Writing for Ryan, CI gates, worktree
  `.env`, secrets), `docs/COVERAGE_HANDOVER.md` (dashboards, identity,
  sweeps, breakthroughs), `docs/BREADTH_SWEEP_BRIEF.md`,
  `docs/YOUTUBE_DRIP_RUNBOOK.md`, `docs/investigations/boarddocs_video_adapter.md`,
  `BACKLOG.md` (read the TOC block, then grep; Standing decisions section
  before "fixing" anything), `BACKLOG_DONE.md` (newest entry first; every
  WO-3xx tonight has one).
- Research: `~/Documents/rtr-business/research/` (`jurisdiction_coverage.csv`,
  `ENUMERATION_METHODS.md` with the write protocol at §158 and reject
  taxonomy at §23, `coverage_registry.csv`, `youtube_channel_leads.csv`,
  `woNNN_*` per WO, `consolidated_governments.csv` in rtr-deeplink for the
  shared-government exception).

## 11. Candidate next work orders (Ryan picks)

1. **Access-ladder fix**: `run_access_ladder()` stops at the first
   vendor-shaped link on a homepage even when it is a decorative clip.
   WO-361, WO-364 and WO-368 all point here: 24 of 30 candidates were promo
   clips and walking those hubs deeper found nothing, so the fix is "try a
   different path off the homepage", not a deeper walk. Top recommendation.
2. **Media-safety fix** in `scripts/wo355_handread.py` and
   `scripts/wo361_handread.py` (Content-Type check before reading a body;
   WO-364 pulled 165 MB into memory before its own fix).
3. **Rerun the WO-366 reverse-query pilot** (50 governments,
   `research/wo366_reverse_pilot.csv`) once Wayback's filtered CDX queries
   answer again; tonight 48 of 50 never answered.
4. **Small-fixes batch**: CivicClerk should delegate Cablecast external
   links via `resolve_via_platform()` (and guard Zoom/WebEx/Drive links as
   not-video); `videoplayer.telvue.com` on `MULTI_GOV_HOSTS`; www-prefix
   retry in `verify_hub()`; Brookline VT YouTube pin evidence lacks a
   state; Sedgwick-style subdomain crowding in the CDX query (main sites
   over 2,000 archived pages fill the cap before subdomains list); Castus
   title-date fallback with Manchester NH as fixture (#1161); Mount Joy
   township PA own-video search plus a Lancaster County Election Board
   mint; the three ambiguous WO-364 candidates (Marion TX, Chesterfield
   Inlet NU, North township IN); a Zoom recording path.
5. **WO-311** verified-pin strength (Ryan approved option a earlier).
6. **WO-352**'s 2,108 remaining rows (Ryan stopped it; resumable).

## 12. Traps learned this round

- A CONFLICTING PR sits forever with "no checks reported"; agents close
  and reopen it or push empty commits. Tell them to rebase.
- `git checkout --theirs` during a rebase of BACKLOG.md silently drops
  main's newer entries. Use the union script and let main's deletions win.
- Agent-reported row counts overstate: line-based commits show fewer rows
  changed because overlapping WOs already wrote the same verdict (WO-361:
  52 → 20; WO-364: 43 → 16). Report Breadth's numbers.
- Leads counts overstate for the same reason (duplicates by video URL).
- The drip does not read the leads file; Ol McClaude reads it by hand and
  queues lines. The drip keeps a line only for YouTube itself or a
  platform in `YOUTUBE_DELEGATING_PLATFORMS` (now civicweb, primegov,
  boarddocs).
- CivicClerk does not delegate Cablecast links, so a CivicClerk queue line
  whose video is Cablecast fails at the worker; queue the direct show URL.
- A CSV rewrite through `csv.writer` normalises thousands of mixed line
  endings in the probe sidecar; edit byte-preserving, append-only.
- Every agent shares the parent session's scratchpad; scratch files are
  named by WO. Agents get a private `agents/<id>/` directory from the hook.
- Internal Archive routes answer 404 on a wrong or missing token; that is
  the token, not the route.
- The research file's `city_name` had 23 double-encoded names (fixed
  5c9a647); a grep for `Ã` finds any recurrence.
