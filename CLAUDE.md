# rtr-deeplink

A deliberately lean rebuild of the video+transcript+deep-link feature from
`rtr-transcripts` (the round-1 "Red Tape Recordings" MVP). No background
job queue — given a meeting URL, resolve its video and transcript on
demand and render them together. There's now an optional database
(`app/db/`) for caching resolves and admin reporting, added deliberately
narrow in scope to avoid reintroducing round 1's Mongo/NextAuth
complexity — it holds no user-facing state today, and the app still works
with zero persistence if it's unset or unreachable. See README's
"Caching and reporting" section for how it works.

**Accounts shipped 2026-08-11 and are live in production** — Clerk-based
sign-in plus saving meetings/searches to your own account, see README's
"Accounts (Clerk)" section for the full architecture. Round 1's mistake
was building full auth/accounts *before validating the core deep-link
feature*, not that accounts themselves were wrong — this repo's own
phase-1 accounts work only started once the core resolve/transcript/
Archive features were already built, tested, and live, and even then
stayed deliberately narrow (accounts + saved items only, via Clerk rather
than a hand-rolled session system, holding zero user PII in this app's
own database). See `BACKLOG.md`'s "Accounts + token billing" section for
what's still ahead (profiles, saved-search alert emails, billing) and
`BACKLOG_DONE.md`'s "Clerk production cutover" entry for the real
incidents hit switching from a Clerk development instance to production —
worth reading before ever touching Clerk env vars/DNS again.

**See `README.md` for architecture, the resolve flow, supported platforms,
and frontend features.** This file covers conventions and context specific
to working on this codebase; don't duplicate README content here.

## Why this exists

Round 1 (`rtr-transcripts`, private repo at github.com/mroconnell/rtr-transcripts,
also cloned locally at `~/Documents/rtr-transcripts`) built a much bigger
product: FastAPI + MongoDB + Beanie, Google OAuth/JWT, a WebSocket-driven
background job queue for Whisper transcription, full search/archive. User
testing showed people wanted two specific things out of all of that: (1) an
approximate transcript for multi-hour meetings, and (2) the ability to
deep-link to a specific timestamp. That feature was already shipped inside
`rtr-transcripts` (see its `docs/video_embed_deeplink_*.md`), just buried
under everything else. This repo extracts and fixes just that part.

## Working conventions established in this repo

- **Never build a platform adapter from assumption — always test against a
  real, live URL first**, ideally several from different cities on that
  platform. Every adapter in `app/platforms/` was built by first fetching
  a real page/API response, reading the actual structure, and only then
  writing the parser. Sample URLs across platforms live in a shared Google
  Sheet the user maintains and adds to over time: "Watchdog Sample meetings
  - Red Tape Recordings - public hearings" —
  https://docs.google.com/spreadsheets/d/1WJvohdOhdUzP0C-0CUfj_pMSjPwYTtMQU3IOeppp54s/edit
  Check it for a real sample before building or debugging any adapter.
  As of 2026-08-08 it has at least one fresh, verified sample for every
  supported platform (rows ~68-77 on the "Sample Meetings" tab) — good
  starting points for caption-parsing work specifically: Dublin CA
  (Swagit, real transcript + agenda together), Boston/Lee's Summit MO
  (Legistar, one clean success + one full-fallback-chain case), Fountain
  Valley CA (Granicus via CivicPlus — also a real edge case: transcript
  genuinely garbled at the source, language misdetected as Portuguese as
  a result; video was missing until the 2026-08-08 fix for
  MediaPlayer.php pages that only embed a legacy Flash/RTMP player — see
  BACKLOG_DONE.md), Whitehall OH
  (CivicClerk, agenda-only), Calgary AB (eScribe, video but no captions
  yet). eScribe's populated-captions gap closed 2026-08-18: Peel Region,
  ON (`pub-peelregion.escribemeetings.com`, real "Regional Council"
  meeting, iSiLIVE video) resolves with 1101 real caption segments, zero
  warnings — add it to the sample sheet alongside the row above.
  CivicClerk's own version of the same gap is still real and unconfirmed
  either way, not addressed by this.
- **Verify in-browser, not just via the API.** UI changes especially need
  an actual `mcp__Claude_Browser__*` check — several real bugs (duplicate
  chapter markers, a metadata-extraction ordering bug, a deep-link
  seek-priority bug) were only caught by looking at the rendered page or
  driving it, not by reading JSON responses.
- **New bugs/gaps found while working go in `BACKLOG.md`**, not just
  mentioned in conversation — it's the durable record. `BACKLOG.md` holds
  only live/open items, kept short on purpose; once an item is actually
  fixed/built and verified, move its entry (marked `[Done YYYY-MM-DD]`,
  full reasoning and verification detail intact) into `BACKLOG_DONE.md`
  rather than marking it done in place — that keeps `BACKLOG.md` fast to
  read while still preserving the investigation history. If a completed
  item left behind a real residual gap (a follow-up not yet built, an
  edge case still unfixed), split that part back out as its own live
  entry in `BACKLOG.md`, cross-linking to `BACKLOG_DONE.md` for context.
- **A PR that ships a feature must update every doc that named it as
  unbuilt, and the PR description must list which.** `README.md`,
  `BACKLOG.md`, and this file all describe real, current gaps — a PR that
  closes one of those gaps but leaves the doc still describing it as
  future/unbuilt work recreates exactly the kind of doc-drift this repo's
  own "App-wide audit" backlog entry already flagged as a real, confirmed
  problem (see this file's pytest-suite bullet above for one concrete
  instance of it), not a hypothetical one.
- **`CLAUDE_BACKLOG.md` is a separate, unreviewed suggestions list**,
  distinct from `BACKLOG.md`. When asked to brainstorm improvements/
  features rather than record a bug or gap found while working, write them
  there instead of directly into `BACKLOG.md` — it holds ideas the user
  hasn't triaged yet, so they don't get mixed in with `BACKLOG.md`'s
  verified, live-tested findings. Once the user accepts an item from it,
  move it into `BACKLOG.md` proper (in that file's style, with real
  verification) rather than marking it done in place.
- **`CLAUDE_INBOX_TRIAGE.md` is a third, separate staging file — set up
  2026-08-17 — populated by a daily *unattended* scheduled Routine, not
  by an interactive session.** The Routine reads Gmail's `rtr-claude`
  label (Search Console, GitHub Actions failure notifications,
  UptimeRobot, eventually Sentry), reasons about each new item using the
  same standards as everywhere else in this file (chase a real report
  when one's reachable — e.g. GitHub Actions logs, via this repo's own
  API access — reason from the alert text plus real code when it isn't,
  e.g. Search Console's auth-walled dashboard; never guess without
  either), and appends findings there. It deliberately never writes
  directly to `BACKLOG.md`/`CLAUDE_BACKLOG.md`/`BACKLOG_DONE.md` — since
  it runs unattended once a day and opens+merges its own PR with no
  human in the loop, writing into files an interactive session might be
  mid-edit on (see the multi-session bullet below) would risk a real
  collision the dedicated file avoids entirely. A human (or a later
  session, explicitly asked) promotes anything that holds up into
  `BACKLOG.md`/`CLAUDE_BACKLOG.md` proper, same pattern as this bullet's
  `CLAUDE_BACKLOG.md` promotion step, then deletes it from the triage
  file rather than marking it done in place. `render.yaml`'s
  `buildFilter.ignoredPaths` (all three services) excludes all four of
  these backlog/triage docs from triggering a Render redeploy, so this
  auto-merging is safe from a production standpoint even with zero human
  review — see that file's own comment.
- **Don't claim a caption/data path works without a positive example.**
  Several adapters have fields that are schema-verified but not
  content-verified (e.g. CivicClerk's `closedCaptionTracks`, Swagit's
  `#transcript-fragments`) because no real meeting with that data
  populated has been found yet — these are explicitly flagged as
  best-effort in code comments and BACKLOG.md, not silently assumed.
- **Synthetic tests (hand-written HTML/JSON, not fetched from a real page)
  are for exercising one specific logic branch already confirmed against
  real data — never a substitute for the "test against a real URL first"
  rule above.** Reach for one only once the adapter's basic real-page
  parsing is already fixture/live-verified, and what's left to cover is a
  narrower edge case (an ambiguous-name collision, a missing-field
  fallback, a rare error path) that no real example has surfaced yet.
  Building one well means two things: (1) the payload's *shape* should
  reuse a schema already confirmed from a real fixture, never an invented
  field structure; (2) the *facts* inside it must be real and
  independently verifiable even though the page/response itself is
  hand-built — e.g. `test_resolve_fills_in_missing_state_via_shared_lookup`
  (`tests/test_civicclerk.py`) uses "Fresno, CA" because it's a
  confirmed-unambiguous real city, not a fabricated one, and
  `jurisdiction_enrich`'s "Kansas City" test relies on that being a real,
  confirmed-ambiguous KS/MO city, not an assumption. Always comment the
  test as synthetic and note what's still unconfirmed (e.g. "no CivicClerk
  customer with a blank `location.state` has been found yet") — that's
  what lets a later read of the suite tell real-verified coverage apart
  from a plausible-but-unconfirmed one, the same distinction the bullet
  above draws for data paths generally.
- **When a platform turns out to be a wrapper around another** (confirmed
  so far: Legistar and CivicPlus both just link out to Granicus, and
  PrimeGov embeds a YouTube video), delegate rather than writing a
  redundant native parser — usually via `resolve_via_platform()` in
  `base.py`, though PrimeGov calls `YouTubeAssetFinder.resolve_video_id()`
  directly instead so it can pass the *original* PrimeGov URL through as
  `source_url` (Legistar/CivicPlus's delegation ends up with the
  delegated platform's URL as `source_url`, a known quirk — see
  BACKLOG.md).
- **yt-dlp is a different kind of dependency than everything else here**
  — every other adapter reads a stable public API or a page structure
  that isn't actively trying to block scraping; YouTube caption fetching
  specifically is (plain HTTP requests to its caption endpoints return
  200 OK with 0 bytes — confirmed live, see BACKLOG.md), and yt-dlp only
  works around that because it's under continuous maintenance chasing
  YouTube's changes. Left unpinned in `requirements.txt` on purpose. If
  YouTube/PrimeGov resolves start failing, check for a yt-dlp update
  before assuming it's a bug in this repo's code.
- **A pytest suite exists now (`tests/`, see README's "Running tests")** —
  run it (`pytest`) before/after touching `app/utils/vtt_parser.py`,
  `app/platforms/media_scan.py`, `app/platforms/base.py`, or any platform
  adapter. Every adapter now has real fixture-backed coverage (see
  README's "Running tests" section for the current, authoritative list —
  this file previously claimed eScribe/PrimeGov/YouTube had zero coverage;
  that was stale as of this correction and is exactly the kind of doc-drift
  this repo's own "App-wide audit" backlog entry flags as a real, confirmed
  problem, not a hypothetical one). It doesn't replace live-testing a new
  adapter or a genuinely new real-world case (see the first bullet above)
  — it exists to catch a *previously-covered* case silently regressing
  between sessions, which live-testing alone doesn't protect against. When
  you fix a bug found via live testing, consider adding a fixture-backed
  regression test for it in the same pass, the way the Simi Valley
  Spanish-caption and blank-VTT cases already are.
- **Every Archive schema change needs an Alembic migration — and that's
  all it needs (WO-10, landed 2026-08-17).** For `archive/`: write the
  migration in `archive/alembic/versions/` (see `archive/alembic/README.md`
  for how), and `render.yaml`'s `preDeployCommand: cd archive && alembic
  upgrade head` runs it *before* the new build starts serving — no shell
  step, no human in the loop, and a failed migration cancels the deploy
  and leaves the old build running. `archive/db/engine.py`'s
  `init_models()` is a **no-op on Postgres** now: `create_all()` runs
  only for the local/test SQLite path, so a model change without a
  migration fails loudly in prod instead of half-working — and CI runs
  `alembic check` against a fresh migration-built SQLite on every PR
  (`.github/workflows/test.yml`), so it fails *before* merge. This
  replaces the earlier guidance that "a brand-new table needs no manual
  migration because `create_all()` runs at startup": that convenience was
  precisely what let `alembic_version` drift silently and produced four
  incidents (2026-08-09/10/13, and the 2026-08-17 `UndefinedColumnError`
  outage when a model column deployed ~13 minutes ahead of its
  `ALTER TABLE` — see BACKLOG_DONE.md). Two rules that follow: **never
  reference a new column in code the same deploy it's added unless the
  code tolerates its absence** (the `search_tsv` feature-detect pattern in
  `crud._fts_available()` is the model — either order deploys safely),
  and **a generated/computed column beats "column + backfill script"**
  when Postgres can compute the value (no ingest change, no one-time
  script, no seam). **The resolver (`app/`) is NOT there yet**: its
  `create_all()` still runs on Postgres and its Alembic history
  (`app/alembic/`, 2 revisions) has never been stamped in prod — the
  one-time `alembic stamp head` on the resolver's Render shell (per
  `app/alembic/README.md`, after confirming `alembic current` is empty
  and the real columns match head) is what unlocks adding the same
  `preDeployCommand` there; tracked in `BACKLOG.md`. Until then a new
  *resolver* table still appears via `create_all()`, and an altered
  resolver table still needs a hand-run migration.
- **`app/db/outcomes.py` classifies reporting outcomes from real signal on
  the row where one exists, and falls back to substring-matching
  `transcript_warnings` only where it doesn't.** `agenda_fallback` is
  decided from `resolved_payload["agenda_items"]` directly (a real field
  on `ResolvedMeeting`, separate from `segments` — see the "Supported
  platforms" table in README.md), not warning text. `garbled_transcript`
  still matches `_GARBLED_MARKER` against `transcript_warnings`, since
  garbled-ness isn't (yet) a first-class field. If you change or add a
  quality warning message in an adapter, keep `_GARBLED_MARKER`'s
  substring intact (or update `outcomes.py` to match) — otherwise that
  warning silently stops being classified correctly and falls through to
  a more generic bucket.

- **This repo is sometimes worked on by more than one session/dev at the
  same time — check before assuming the working tree is yours alone.**
  Real, repeated situation on 2026-08-08: another session was actively
  committing extensive changes (a pytest suite, RSS feed, PWA manifest, a
  transcript language picker, a real bug fix) while this session was
  running in parallel, sharing the same local clone. Concretely: **always
  run `git status` before editing**, and if it shows unrelated
  uncommitted changes that aren't yours, don't touch them — don't stage
  them, don't revert them, don't let them ride along in your commit. If
  you need to land your own change cleanly without disturbing that
  other in-progress work, isolate it: `git worktree add /tmp/some-name
  origin/main`, make your edit there, commit, push (a plain `git push
  origin <branch>` — pushing a differently-named local branch directly
  onto `main` via refspec, or force-recreating a local `main` with `-B`,
  both got flagged by the auto-mode safety classifier; a normal
  `gh pr create` + `gh pr merge --squash --delete-branch` from the
  worktree works reliably instead), then `git worktree remove
  <path> --force` to clean up. If `origin/main` has moved again by the
  time you push (it will, if the other session is active), `git fetch`
  + inspect *what* changed (`git log --oneline main..origin/main`)
  before reconciling — often it's your own already-merged work the local
  branch just hasn't caught up to yet, not a real conflict; `git pull
  --rebase` handles the genuine case cleanly as long as your change and
  theirs touch different regions of the file.
- **Never `grep`/`cat`/`Read` a gitignored file (`.env`, credentials,
  anything matching `.gitignore`) with a pattern broad enough that a
  secret's plaintext value could end up echoed into the conversation.**
  Real incident, 2026-08-11: a `grep -n "DATABASE_URL\|ARCHIVE"` intended
  to check whether `DATABASE_URL` was set also matched `.env`'s
  `ARCHIVE_INGEST_TOKEN=...` line and printed its real value verbatim —
  the sed redaction in place only masked `user:pass@host`-shaped DB URLs,
  not an arbitrary token. Required rotating that token in all 3 places it
  lives (both Render services' dashboards + local `.env`) after the fact.
  If a specific env var's value is genuinely needed, ask the user for it
  directly rather than reading it out of `.env` yourself; if only
  *presence* matters, use a check that doesn't print the value at all
  (e.g. `grep -q '^SOME_KEY=' .env && echo set || echo unset`, or `python
  -c "import os; print(bool(os.environ.get('SOME_KEY')))"` for an
  already-loaded process). Application code loading `.env` via
  `load_dotenv()` at runtime (as `app/main.py`/`archive/main.py` already
  do) is fine — the risk is specifically a shell command whose *output*
  lands in the conversation.

## Related context

The essentials (why this pivot happened, per-platform findings, known
gaps) are captured directly in this repo — `README.md`, this file, code
comments, and `BACKLOG.md` (plus `BACKLOG_DONE.md` for completed items and
`CLAUDE_BACKLOG.md` for unreviewed, Claude-proposed ideas) — deliberately,
so a session opened straight against this repo has what it needs without
depending on anything else.

**Business context lives outside this repo, on purpose.** Admin, planning,
strategy, research, and marketing for Red Tape Recordings are worked on in
`~/Documents/rtr-business` (its own CLAUDE.md, task backlog, and topic
folders, plus a linked Claude.ai Project). Product *roadmap* items still
live here in `BACKLOG.md`'s "Archive roadmap" section, next to the
constraints that shape them — that workspace reads them rather than
duplicating them. Keep code work in this repo and business work there; don't
let either drift into the other.

Deeper session narrative (the original round-1 user-testing conversation,
day-by-day investigation detail) lives in Claude Code auto-memory scoped
to `~/Documents/rtr-transcript` — the *original* project directory this
one was spun out of, not this one. A Claude Code session opened at
`~/Documents/rtr-deeplink` (e.g. from VS Code) will *not* auto-load that
memory, since memory is scoped per working directory. It's rarely needed
day to day; if something here references a decision that isn't explained
in-repo, that's where to look, or just ask the user.
