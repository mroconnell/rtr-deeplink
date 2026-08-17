# Audit execution brief — rtr-deeplink

**Source:** `AUDIT_2026-08-14.md` (in this repo root and in `rtr-business/`)
**For:** Claude Code sessions working against `rtr-deeplink`
**Written:** 2026-08-14, against commit `bf3ef7f`
**Re-sequenced 2026-08-16:** Phase 2/3 re-grouped into six waves after a
roadmap-planning pass (reliability/ops lens, ~2-4 week horizon). Status
corrected against a live code check the same day: **WO-5 (SSRF guard) is
done** — it shipped since this brief was written but was still listed as
open below; everything else in Phase 2/3 was reconfirmed genuinely still
open (`app/main.py:270-272`/`archive/main.py:109-111` still return static
`{"status": "ok"}`, `app/main.py:1167`'s admin-token check is still
query-param only, `requirements.txt` is still fully unpinned, no
`databases:` block in `render.yaml`, no Sentry import anywhere, no lint
config). Four new work orders (WO-13 through WO-16) were folded in from
`BACKLOG.md`/`CLAUDE_BACKLOG.md` since they sit inside the same lens. The
underlying Problem/Do/Acceptance detail for WO-4 through WO-12 is
unchanged from 2026-08-14 — only status, sequencing, and grouping changed.

Twelve-plus work orders, in dependency order within each wave. Each is
sized to one PR. Pick one,
do it completely, land it, move on — do **not** batch several into one
branch. Several of these touch deploy-time behaviour, and a mixed PR makes
a bad deploy impossible to bisect.

---

## Before you touch anything

Four hazards specific to this repo. All are documented in `CLAUDE.md`; they
are repeated here because every work order below is affected by at least one.

1. **A merge to `main` deploys to production immediately.** `render.yaml`
   Blueprint sync fires on every push. A CI test gate now exists and
   branch protection is verified to actually block a failing merge (WO-2,
   done — see Phase 1 below), but that only blocks merges with a failing
   test, not merges with a passing test and a bad live consequence. Treat
   every merge as a production deploy you are personally responsible for
   verifying.
2. **This clone may be shared with another active session.** Run `git
   status` first. If there are uncommitted changes that aren't yours, don't
   touch them — isolate your work with `git worktree add /tmp/<name>
   origin/main`, then `gh pr create` + `gh pr merge --squash
   --delete-branch` from the worktree. Do not push a differently-named
   branch onto `main` via refspec; it gets flagged.

   **Hard rule, added 2026-08-14 after a real incident:** never run `git
   reset --hard`, `git checkout .`, or `git clean -fd` without running
   `git stash -u` immediately before it — not "unless you checked," not
   "unless the tree looked clean earlier." A session running WO-1 through
   WO-3 did its `git status` check at session start, then ran `git reset
   --hard origin/main` later in the same session and destroyed another
   session's uncommitted `BACKLOG.md` edits (recovered via `git reflog`).
   The check was correct; it was just stale by the time the destructive
   command ran. The stash is what binds at the right moment.
3. **Never grep a gitignored file with a broad pattern.** A real incident on
   2026-08-11 echoed `ARCHIVE_INGEST_TOKEN`'s plaintext value into a
   transcript and forced a rotation in three places. If you need an env
   var's value, ask Ryan for it.
4. **Schema changes are not automatic.** `create_all()` handles new tables;
   altering an existing table needs Alembic, run by hand against prod. See
   WO-10 — this is the single most incident-prone area of the repo.

**Definition of done, every PR:**

- `pytest` passes locally, and `npm test` if you touched JS.
- Any doc that made a claim your change invalidates is updated **in the same
  PR** — `README.md`, `CLAUDE.md`, `BACKLOG.md`, and
  `../rtr-business/BUSINESS_OVERVIEW.md` are all in scope. The PR
  description lists which docs you touched and why.
- The corresponding `BACKLOG.md` entry moves to `BACKLOG_DONE.md` with the
  investigation detail, per existing convention.
- If the change affects production behaviour, the PR description says how
  you verified it live, or says explicitly that you couldn't.

---

## Prerequisites Ryan owns

These are dashboard checks, not code. Three work orders are blocked on them.

| # | Check | Blocks |
|---|---|---|
| P1 | ~~Render → both Postgres instances: what plan?~~ **ANSWERED 2026-08-14:** `rtr-deeplink-db` is **Basic-256mb** (paid, ~$6/mo) — not at risk. Staging is free and expires 9/9/2026, which is intentional and disposable. Remaining sub-questions folded into WO-4 below. | WO-4 (Wave 4), WO-10 (Wave 5) |
| P2 | ~~Render → all three services: does the live plan match `render.yaml`? Current month's actual bill?~~ **ANSWERED 2026-08-17:** plans basically match. Real bill via CSV export: **$16.26 month-to-date, $49.10 projected for August** — recorded in `rtr-business/BUSINESS_OVERVIEW.md`. One real anomaly surfaced, not yet explained: both the resolver and Archive show billed hours on *both* `starter` and `standard` tiers this month despite `render.yaml` declaring `starter` for both — noted in `BUSINESS_OVERVIEW.md`, not investigated further this pass. Bandwidth is worth watching: 5.13GB/5GB included this month, close to real overage. | WO-4 (Wave 4) |
| P3 | GA: is the property receiving events? Are `submit_meeting_url` and `copy_link_to_time` visible in the last 30 days? | WO-9 (Wave 3) |
| P4 | ~~Resend + Clerk: plan, cost, distance from free-tier ceiling.~~ **ANSWERED 2026-08-17:** both free tier, well under ceiling. | WO-4 (Wave 4) |
| P5 | Actions → a recent `send-search-alerts` run: did a real alert email actually send? | — (informational) |

**P1 was the highest-consequence unknown in the audit and is already
answered** (see above). What's left blocking is P2 and P4 (both gate Wave
4) and P3 (gates Wave 3) — worth asking Ryan for these early, since
they're quick dashboard checks that would otherwise stall a wave mid-way.

---

## Phase 1 — before outreach starts · **COMPLETE 2026-08-14** (PRs #46, #47, #48)

WO-1 and WO-2 landed as specified. **WO-3's premise was wrong** — `.claude/`
was never tracked in this repo (verified with `git log --all -- .claude/`,
empty across all branches). The audit inferred tracking from `.gitignore`
lacking the entry plus those files being present on disk; the copy it was
reading had `.git` stripped, so tracking was never actually checkable. The
`.gitignore` entry landed anyway as free insurance. Treat this as a
reminder that the audit's UNVERIFIED markers were load-bearing.

**WO-2 paid for itself immediately**, and in a way worth recording: both
bugs it surfaced were *environment-masking* bugs, not code bugs. Bare
`pytest` wasn't putting the repo root on `sys.path` (fixed with `python -m
pytest`), and two nav tests were silently reading a real
`CLERK_PUBLISHABLE_KEY` out of the local `.env` (fixed by defaulting it in
`conftest.py`, matching the existing `ARCHIVE_INGEST_TOKEN` /
`ADMIN_STATS_TOKEN` pattern). Until PR #47, "pytest passes" was partly a
statement about one laptop rather than about the code — which is precisely
the failure mode the suite was built to prevent.

**Branch protection landed and was verified 2026-08-14** — a ruleset on
`main` requiring the `test` check, confirmed to actually block merge (not
just show red) with a throwaway failing-test PR; see `BACKLOG_DONE.md`'s
"Testing infrastructure" section for the full record, including two
follow-up refinements (the dual-trigger fix, squash-only merges). **Still
open, Ryan's:** the Search Console sitemap re-submission.

### WO-1 · Fix `robots.txt` prefix match — **~15 min**

**Problem.** `app/main.py:1116-1119` emits `Disallow: /meeting`. robots.txt
matches by prefix, so this also blocks `/meetings` — the Archive's browse
and search hub (`archive/main.py:588`), which is simultaneously advertised
as indexable in the sitemap (`archive/main.py:667`).

**Do.** Replace the single directive with two: `Disallow: /meeting$` and
`Disallow: /meeting?`. Keep the existing explanatory comment and extend it
to note the prefix-match trap, so this isn't reintroduced.

**Acceptance.**
- A unit test asserts the emitted body contains both anchored forms and
  does **not** contain a bare `Disallow: /meeting` line.
- A test asserts `/meetings` is not matched by the emitted rules.
- After deploy: fetch `https://redtaperecordings.com/robots.txt` and confirm
  the new body. Re-submit the sitemap in Search Console and confirm
  `/meetings` is no longer reported as blocked.

**Note for Ryan, not the implementer:** Search Console will take days to
re-crawl. Landing the fix is the deliverable; the index recovering is not.

### WO-2 · CI test gate + branch protection — **~1 hr**

**Problem.** `.github/workflows/` holds only two `curl` cron jobs. Nothing
runs the 658-function suite. Merges to `main` auto-deploy ungated.

**Do.** Add `.github/workflows/test.yml` on `push` and `pull_request`:
checkout, `actions/setup-python` pinned to **3.12.3** (matching
`render.yaml:55-56`; local dev is on 3.13 and that difference is currently
untested), `pip install -r requirements.txt -r requirements-dev.txt`,
`pytest`, then `npm ci && npm test`.

The suite is hermetic — `tests/conftest.py:13-30` pins a temp SQLite DB,
HTTP is mocked, Playwright is monkeypatched. **No** network, Postgres, or
`playwright install` step is needed. If you find yourself adding one, stop
and work out why.

**Do first:** run the full suite locally on 3.12.3 before opening the PR. If
it's currently red, fix that in a separate PR — a required check that fails
on day one blocks every merge.

**Acceptance.** Workflow green on its own PR. Then Ryan enables branch
protection on `main` requiring it. Confirm by opening a throwaway PR with a
deliberately failing test and checking the merge button is blocked.

### WO-3 · Stop shipping machine-local config — **~5 min**

**Problem.** `.gitignore` covers `.env`, `*.db`, `.venv` correctly, but not
`.claude/`. So `settings.local.json` (which pre-approves `Bash(git push *)`
for every session that clones this repo) and `launch.json` (which hardcodes
`/Users/mroconnell/...`) ship to everyone.

**Do.** Add `.claude/` to `.gitignore`, then `git rm --cached` the two
tracked files. Do not delete them locally.

**Acceptance.** `git ls-files | grep '^\.claude/'` returns nothing.

---

## Wave 1 — make failures visible · **COMPLETE 2026-08-16**

No blockers. ~1-2 days. Do these first — each is cheap and makes some
other failure mode observable that is currently silent.

All four items (WO-5, WO-6, WO-8, WO-7, WO-13) are done. Ryan's WO-7
account setup is done too — `SENTRY_DSN` and `UPTIME_CHECK_URL` are both
live on the resolver, `/api/health/resolve-check` verified returning
`{"status":"ok"}` in production. Only optional loose end: an
`ALERT_WEBHOOK_URL` repo secret (Slack/Discord), shared by all three cron
workflows, still unset. Wave 2 (dependency & code hygiene) has no
blockers and can start any time.

### WO-5 · SSRF guard on the resolve entrypoint — **DONE**

Shipped since this brief was written (`app/utils/url_guard.py`), still
listed here so the dependency history stays legible. Original spec, for
reference: `ResolveRequest.url` was a bare `str` and unknown hosts fell
through to the generic fallback's `session.get(url,
allow_redirects=True, ...)` with no scheme allowlist, no private-IP
rejection, no per-hop redirect check, and no response-size cap, while
`GENERIC_FALLBACK_HEADLESS=1` meant a real browser would fetch whatever
it was pointed at. Fixed with a shared helper applied at the resolve
entrypoint and the generic fallback's own fetches, including the headless
escalation. See `BACKLOG.md`'s App-wide-audit section for the closure
note.

### WO-6 · Health checks that can fail — **DONE 2026-08-16**

**Problem.** `render.yaml:47,128` gate deploys on `/api/health`, and both
handlers return a static `{"status": "ok"}` (`app/main.py:268-270`,
`archive/main.py:109-111`). During the 2026-08-09 incident the app was
failing every query on a missing column and would still have reported `ok`.

**Do.** Execute `SELECT 1` (and on the Archive, a cheap count against one
real table). Return 503 with a short reason on failure. Keep it cheap —
Render polls this frequently.

**Fixed.** Both handlers now open a real DB connection before reporting
`ok` — the resolver runs `SELECT 1`, the Archive runs a cheap
`SELECT count(*)` against `MeetingPage` (catching a missing/misnamed table,
not just a dead connection). Either raises → `logger.exception` +
`{"status": "error", "reason": "database unreachable"}` at 503. Both
handlers do the DB import locally inside the function, matching the
existing `/internal/schema-info` pattern (`archive/main.py`) rather than
adding new module-level imports.

**Acceptance.** `tests/test_health_endpoint.py` covers all four cases (both
services × reachable/unreachable), full suite still green (789 passed). DB
unreachability is simulated by swapping the module-level `engine` object
for a stub whose `.connect()` raises — `AsyncEngine.connect` turned out to
be a read-only attribute, so patching a method onto the real engine
instance doesn't work; swapping the whole object does, since the handler
re-imports `engine` from `.db.engine` on every call. **Still open, not
done in this pass:** confirming in Render that the health-check gate
actually fails a deploy when the endpoint reports unhealthy — that needs a
real deploy to verify, not something a local session can confirm.

### WO-8 · Admin token out of the URL — **DONE 2026-08-16**

**Problem.** `daily-report.yml:38` and `send-search-alerts.yml:37` both send
`?token=${{ secrets.ADMIN_STATS_TOKEN }}`. GitHub masks it in Actions logs;
Render's request logs do not. The Archive already does this correctly at
`archive/main.py:100-106`.

**Do.** Accept `Authorization: Bearer` on the admin routes in `app/main.py`,
keeping query-param support temporarily so the switch isn't a flag day.
Update both workflows to `curl -H`. Then remove the query-param path in a
follow-up once you've confirmed both crons ran green.

**Fixed.** `_admin_token_ok()` now checks `Authorization: Bearer` first and
falls back to the `token` query param only if no (or a malformed) header is
present — still `secrets.compare_digest`, not `==`. All 9 `/admin/*` routes
(one more than the audit's original count: `/admin/stats`,
`/admin/daily-report`, `/admin/send-search-alerts`, `/admin/log`,
`/admin/problem-reports`, `/admin/recheck-archive-page`,
`/admin/sweep-pending-pushes`, `/admin/promote-transcript-version`,
`/admin/correct-transcript-language`) now take an `authorization` header
param. Both cron workflows (`daily-report.yml`, `send-search-alerts.yml`)
switched to `curl -H "Authorization: Bearer ..."`; the query-param path is
deliberately still live for now, per the "not a flag day" instruction.

**Acceptance.** `tests/test_admin_token_auth.py` (new) covers: no
credentials → 404, correct/incorrect header → 200/404, correct/incorrect
legacy query param → 200/404, header takes priority when both are present,
and a malformed (non-`Bearer`-shaped) header falls back to the query param
rather than hard-rejecting. Full suite green (796 passed). **Still open,
Ryan's:** confirm both workflows actually run green against the deployed
header-auth change, then remove the query-param fallback in a follow-up PR
— not done in this pass, since it needs a real cron run against prod to
confirm before it's safe to remove.

### WO-7 · Know when production breaks — **CODE DONE 2026-08-16, needs Ryan's accounts**

**Problem.** No error monitoring exists; `CLAUDE_BACKLOG.md:28-31` concedes
that "production exceptions currently only surface if someone happens to
check Render logs." The daily digest degrades silently by design —
`app/reporting.py:53-60` lets one metric fail without blanking the others,
so `curl --fail-with-body` sees HTTP 200 on a half-broken report.

**Do.** (a) Sentry free tier on both web services and the worker, with the
DSN as an env var and a no-op when unset, matching how Clerk degrades. (b) An
external uptime check against a **real resolve path**, not `/api/health`.
(c) Add `if: failure()` notification steps to both existing workflows. (d)
Make `/admin/daily-report` return a non-2xx when any metric errored, so the
cron's `--fail-with-body` actually trips.

**Fixed — code side.**
- (a) `_init_sentry()` (duplicated per service, same pattern as
  `clerk_auth.py`) calls `sentry_sdk.init()` before the app/worker loop
  starts, only when `SENTRY_DSN` is set. Its default logging integration
  means every existing `logger.exception()`/`logger.error()` call across
  all three services starts reporting with **no per-call-site changes** —
  this was the actual leverage, not manually instrumenting each one.
- (b) New `GET /api/health/resolve-check` — unlike `/api/health`, this
  runs a real resolve (via the same cache-then-live-adapter path
  `/api/resolve` itself uses) against one operator-chosen URL
  (`UPTIME_CHECK_URL`), so a plain GET from any free-tier uptime service
  proves the whole pipeline, not just the DB. Returns `not_configured`
  (still 200) when the env var is unset — this endpoint existing must
  never be what breaks a dashboard on its own.
- (c) Both `daily-report.yml` and `send-search-alerts.yml` got an
  `if: failure()` step that posts to `ALERT_WEBHOOK_URL` (Slack/Discord
  incoming webhook) when set, and logs a `::warning::` annotation
  otherwise — GitHub's own failed-scheduled-workflow email is the
  fallback either way, so this is additive, not the only signal.
- (d) `run_daily_report()` now returns each metric's jsonable
  `{value, error}`; `/admin/daily-report` checks `failed_metric_names()`
  first (ahead of the existing send-failure check) and returns 502
  `metrics_unavailable` with the list of which metrics failed.

**Still open — Ryan's, not code:**
1. ~~Create a Sentry account (free tier), set `SENTRY_DSN` on all three
   Render services.~~ **Done 2026-08-16** — DSN uploaded. Not yet
   independently verified that a real raised exception actually shows up
   in the Sentry dashboard (see Acceptance below).
2. ~~Create an external uptime-monitor account (e.g. UptimeRobot, Better
   Uptime), point a GET check at `/api/health/resolve-check`, and set
   `UPTIME_CHECK_URL` on the resolver to a real meeting URL you're
   comfortable being polled repeatedly (most polls will hit cache, not
   re-fetch the source site — see the endpoint's own docstring).~~ **Done
   and verified live 2026-08-16** — UptimeRobot configured,
   `UPTIME_CHECK_URL` set to `https://simivalley.granicus.com/player/clip/2840`
   (real Granicus meeting, video + populated transcript, plain HTTP
   adapter — deliberately not a headless-browser platform or YouTube, to
   avoid unrelated false alarms). Took a manual "Deploy latest commit" to
   actually pick up the env var — a plain service restart didn't do it,
   worth remembering next time this comes up. `curl
   https://rtr-deeplink.onrender.com/api/health/resolve-check` now
   returns `{"status":"ok"}`.
3. Optional, still open: an `ALERT_WEBHOOK_URL` repo secret (Slack/Discord
   incoming webhook) for (c) above.

**Acceptance.** A deliberately raised exception on a staging path appears in
Sentry — **not verified**, DSN is set but this specific check hasn't been
run. A forced metric failure turns the daily-report workflow red —
**verified**, covered by
`tests/test_daily_report.py::test_admin_daily_report_returns_502_when_a_metric_failed`
plus the full suite (808 passed). `tests/test_health_resolve_check.py` and
`tests/test_sentry_init.py` cover the new endpoint and the no-op/init gate.

### WO-13 · Adapter health canary — **DONE 2026-08-16**

**Problem.** The test suite and WO-7's Sentry both catch code-level
failures, but neither catches the failure mode this repo hits most often
in practice: a government site quietly changes its page/API structure and
a working adapter starts returning empty or wrong data while still
returning HTTP 200 — no exception, nothing for Sentry to see. A past
session flagged this as **"still the highest-value remaining item"** in
`CLAUDE_BACKLOG.md`, unreviewed/unaccepted until this planning pass.

**Do.** A scheduled job (reuse the existing GH Actions cron pattern) that
re-resolves one known-good URL per supported platform — the same URLs
already used as `tests/fixtures/` sources are a natural starting list —
and alerts (reuse WO-7's notification path) when a previously-successful
platform starts coming back empty/error. Keep it cheap: one URL per
platform, not a full crawl.

**Fixed.** `scripts/adapter_canary.py` calls each platform's real
`AssetFinder.resolve()` directly (in-process, not via the deployed HTTP
service — no dependency on the app being up, no canary noise written into
production's cache/stats/Archive) against one real, confirmed-good URL per
platform, pulled from that platform's own test fixtures (picking the
richest positive example where a test file had more than one real
candidate). `.github/workflows/adapter-canary.yml` runs it daily
(distinct cron time from the other two cron workflows — no Render
resource-contention reason to cluster with them) with the full dependency
set plus `playwright install chromium` (two platforms, LIMS/SLC, are
genuinely headless-browser-gated), and reuses WO-7's exact
`if: failure()` → `ALERT_WEBHOOK_URL`-or-`::warning::` notification step.

A `CalendarPageError` (a listing/calendar page rather than one meeting --
e.g. CivicPlus's AgendaCenter, which has no single-meeting URL shape at
all) with real candidates found counts as a pass, not a failure — a real
regression there would show up as the candidate list going empty, not as
the routing behavior itself.

**Two platforms deliberately excluded from `CANARY_URLS`, not guessed at**
— `scripts/adapter_canary.py`'s own comment has the full reasoning:
- **swagit**: no real Swagit meeting URL exists anywhere in this repo's
  text at all (`tests/test_swagit.py`'s own header says so).
- **civicplus**: the one site this adapter was ever verified against
  stopped resolving 2026-08-07 (already documented in
  `tests/fixtures/civicplus/README.md`), re-confirmed dead by a live DNS
  failure building this canary. New `BACKLOG.md` entry (Platform coverage
  section) records this and names an untested replacement candidate
  (Maricopa County, AZ).

**Acceptance.** Running live against today's adapters: **20/20 platforms
pass** (confirmed 2026-08-16, real network calls against real government
sites, not mocked — `python scripts/adapter_canary.py`). Deliberately
breaking one adapter's parsing locally (a fixture-based fake finder
returning an empty `ResolvedMeeting`, plus a second case for a
`CalendarPageError` with zero candidates) produces a real reported
failure, not a silent pass — `tests/test_adapter_canary.py` (10 tests, no
real network calls, matching this suite's hermetic convention). Full
suite green (818 passed).

---

## Wave 2 — dependency & code hygiene · **COMPLETE 2026-08-16**

No blockers, parallel-safe with any other wave. ~1 day.

Both items (WO-11, WO-12) done. A real Render deploy off the new pinned
lockfiles (WO-11's acceptance criterion) still hasn't happened this
session — worth confirming next deploy. Wave 3 (outreach measurability)
has no blockers and can start any time.

### WO-11 · Pin dependencies, then scan them — **DONE 2026-08-16**

**Problem.** Every entry in all three requirements files uses `>=` with no
upper bound and no lockfile, while `render.yaml:40,126` reinstall on every
deploy — so two deploys of identical source can install different versions.
No Dependabot, no `pip-audit`.

**Do.** `pip-compile` a lockfile per service. **Keep `yt-dlp` deliberately
loose** with a comment pointing at `CLAUDE.md:128-136` — YouTube actively
breaks scrapers and yt-dlp only works because it chases them; pinning it is
a bug, not hygiene. Same reasoning for `faster-whisper` in the worker. Then
enable Dependabot (only useful once versions are pinned) and add `pip-audit`
to the WO-2 workflow as a non-blocking job first, blocking once the initial
noise is triaged.

**Fixed.** Each service now has a `requirements.in` (loose source, all the
existing explanatory comments preserved) compiled via `pip-compile` into a
fully-pinned `requirements.txt` (the actual install target, unchanged).
`yt-dlp` (resolver + worker), `faster-whisper` (worker), and
`youtube-transcript-api` (dev-only) are excluded from each `.in` file and
appended unpinned by hand to the compiled `.txt` afterward, each with a
comment explaining why and a reminder to re-append after the next
`pip-compile` run — pip-compile has no native "leave this one floating"
flag, so this is a deliberate manual step, not an oversight. `.github/
dependabot.yml` covers all three service directories (`/`, `/archive`,
`/worker`), weekly. `pip-audit` added as a non-blocking step in
`test.yml`, scanning all four requirements files (resolver, dev, archive,
worker) — today's scan is clean across all four (no known
vulnerabilities), so there's no real "initial noise" to triage before
flipping it blocking, but it's left non-blocking per the work order's own
instruction, since that's really about tolerating a *future* CVE
disclosure without silently blocking every merge, not about today's
clean result.

**Acceptance.** Verified locally rather than via a real Render deploy (no
prod access this session): `pip install -r requirements.txt
-r requirements-dev.txt` into the working venv, full suite green (818
passed) — including a real major-version bump surfaced by pinning
(`clerk-backend-api` 6.0.1 → 7.0.0) that turned out compatible.
`archive/requirements.txt` and `worker/requirements.txt` each verified to
install cleanly in their own isolated scratch venv, matching how they
actually deploy (separate Render services, never installed together).
`yt-dlp`/`faster-whisper`/`youtube-transcript-api` confirmed still
unpinned in the final compiled files. A real Render deploy per service is
still the strongest verification and hasn't happened yet — worth
confirming after this merges.

### WO-12 · Linter and formatter — **DONE 2026-08-16**

**Problem.** No ruff/black/mypy/pre-commit config anywhere. Given that
multiple sessions edit this tree the same day, a formatter is mostly about
keeping `git pull --rebase` clean — gratuitous whitespace diffs are what
turn a clean rebase into a conflicted one.

**Do.** Add `ruff` (lint + format in one tool) to `requirements-dev.txt`, a
minimal config block, and a `ruff check` / `ruff format --check` step in the
WO-2 workflow. Land the bulk reformat as its **own** commit so it doesn't
poison `git blame` on the config commit.

**Fixed, in two PRs** (this repo's branch protection is squash-merge-only,
so two PRs was the only way to actually get two separate commits on
`main` — a single PR with two commits would have collapsed into one on
squash):
- **PR #90** (config): `ruff.toml`, deliberately minimal — `select =
  ["E", "F", "W"]`, `ignore = ["E402", "E501"]`. `E402` excluded because
  this repo intentionally imports several modules only after
  `load_dotenv()`/`_init_sentry()` run (a real, documented pattern, not
  an accident); `E501` excluded because this codebase's comments/
  docstrings are deliberately prose-length, and `ruff format` doesn't
  rewrap comments anyway. Also fixed the 13 real findings that selection
  surfaced (7 unused imports, 2 unused local variables, 2 ambiguous
  single-letter variable names, 2 trailing-whitespace lines in
  Alembic-generated migration docstrings) and added `ruff check` as a
  blocking CI step.
- **PR (this one)** (reformat): ran `ruff format` across `app/`,
  `archive/`, `worker/`, `scripts/`, `tests/` — 144 files reformatted, 27
  already compliant. Added `ruff format --check` as a blocking CI step
  now that the codebase is compliant.

**Skip mypy.** Retrofitting types here is a multi-day project with unclear
payoff at this stage — not done, not attempted.

**Acceptance.** `ruff check` and `ruff format --check` both pass cleanly.
Full suite green post-reformat (835 passed — up from 818 at the start of
this wave, entirely from real peer work merged concurrently in between,
confirmed via `git log`, not from the reformat itself). Coordinated with
4 active peer sessions before running the repo-wide reformat, given its
blast radius (144 files) — all confirmed clear first.

---

## Wave 3 — outreach measurability · **COMPLETE 2026-08-16**

No code blockers, but **coordinate the UTM convention with Ryan before any
real outreach send** — see below. ~1 day.

WO-9 done, including a real GA gap on Archive found and fixed along the
way (see below). Still needs Ryan's side: settle the UTM convention
before any real outreach email goes out. Wave 4 (infra into the
Blueprint) is next but needs Ryan's dashboard checks (P2, P4) first;
Wave 6 (recurring bug-class cleanup) has no blockers and could run in
the meantime.

### WO-9 · The three events that make outreach measurable — **DONE 2026-08-16**

**Problem.** Five GA events exist (`submit_meeting_url` at
`app/templates/index.html:26`, three `copy_link_to_time` in `player.js`, one
`newsletter_signup`). Missing: whether a resolve **succeeded**, whether
anyone **played** the video, and any way to attribute a visit to an outreach
recipient.

**Do.** Fire `resolve_result` with `{status, platform}` from the resolve
response handler; `video_play` and `transcript_seek` from `player.js`, which
already has `trackEvent` in scope. Keep params low-cardinality — no URLs, no
anything user-identifying.

**Fixed.**
- `resolve_result` fires at all four `/api/resolve` response branches in
  `player.js`: `{status: 'success', platform}`, `{status: 'redirect'}` (no
  platform — the redirect response never carries one), `{status:
  'calendar_page', platform}`, and `{status: <error code>, platform}` for
  `blocked_url`/`unsupported_platform`/`resolve_failed`. Status values are
  always one of a small fixed set, never free text (`data.message` is
  never sent).
- `transcript_seek` fires from the real transcript-line click handler
  (`renderTranscript`'s `.segment-timestamp` listener) — deliberately not
  wired into agenda-item clicks, which reuse the same CSS class but are a
  separate feature.
- `video_play` fires from the one shared `adapter.addEventListener('play',
  ...)` that already covers every video backend (native/YouTube/Viebit).
  **Real bug found and fixed while wiring this up**: the native adapter's
  own muted play-then-pause warm-up trick (`initNativeVideo`, briefly
  autoplays-then-pauses to pre-buffer) fires the exact same native `play`
  event this listener was hooked to — without a fix, `video_play` would
  have fired on **every page load**, not just real user-initiated plays,
  making the whole metric meaningless. Fixed with a module-level
  `suppressWarmupPlayTracking` flag, set for the duration of the warm-up
  sequence only. Confirmed live (see Acceptance) that a page load alone no
  longer fires it, and a real play does.
- **Second real gap found and fixed, not in the original WO-9 scope**:
  Archive (`archive/main.py` + `archive/templates/base.html`) had **no
  Google Analytics at all** — no `gtag`, no `GA_MEASUREMENT_ID` global,
  nothing, unlike the resolver. Since a large fraction of real traffic
  redirects from `/meeting` straight to a permanent `/m/{slug}` page, any
  outreach visit landing there would have been completely invisible to
  GA regardless of whether UTM params survived the redirect — undermining
  WO-9's whole point for exactly the visits most likely to matter. Fixed
  by mirroring the resolver's exact `GA_MEASUREMENT_ID` global +
  conditional `gtag`/`trackEvent` snippet onto Archive's `base.html`.

**Ryan's half, and it needs no code:** every personalized link in the
first-10 campaign gets
`?utm_source=outreach&utm_campaign=first10&utm_content=<recipient-slug>`.
GA segments on that automatically. **This is unrecoverable if the first
emails go out without it** — settle the convention before sending. This
directly unblocks the outreach-tracking prerequisite already flagged as
open in `rtr-business/TASKS.md`.

**Acceptance.** All three events verified live against a local dev server
and a real Granicus meeting (Simi Valley), not just read from code —
`window.dataLayer` inspected directly in-browser after each action:
`resolve_result` fires with `{status: 'success', platform: 'granicus'}` on
a successful resolve; `video_play` does **not** fire on page load (warm-up
suppressed) but **does** fire on a real play-button click; `transcript_seek`
fires on a real transcript-line click. UTM survival confirmed live too:
navigating to `/meeting?url=...&utm_source=outreach&utm_campaign=first10
&utm_content=test-recipient` for an already-archived meeting redirected to
`/m/{slug}?utm_source=outreach&utm_campaign=first10&utm_content=
test-recipient` — params fully intact. Archive's new GA snippet confirmed
rendering on a local Archive instance. Full suite green (836 passed), JS
suite green (29 passed), `ruff check`/`ruff format --check` clean.

---

## Wave 4 — infra into the Blueprint + backup/restore · **DONE 2026-08-17**

P1, P2, P4 all now answered (see the Prerequisites table above).

### WO-4 · Bring infra into the Blueprint + finish the cost inventory — **1-2 hrs** · *blocked on P1, P2, P4*

**Problem.** `render.yaml` has no `databases:` block, so both Postgres
instances live outside tracked config. The file's own header records a real
incident where a push silently reverted manually-set paid plans back to
`free` — which would reintroduce the cold starts that hurt crawl health on
`/m/*`. `DATABASE_URL` is `sync: false` on three services with a prose
comment (`render.yaml:181`) that two of them "MUST" match, and nothing
checks it.

**Do.** Add a `databases:` block for `rtr-deeplink-db` (Basic-256mb,
confirmed 2026-08-14). Deliberately exclude the free staging instance, with
a comment saying it's disposable and expires 9/9/2026 — so a future reader
doesn't "fix" its absence. Add a startup log line on the worker and Archive
asserting their `DATABASE_URL` hostnames match, failing loudly if not.
Record the confirmed monthly total in `rtr-business/BUSINESS_OVERVIEW.md`
(replacing the current partial figure) with the date it was confirmed.

**Three sub-questions P1 left open — resolve these as part of this WO:**

1. **Storage headroom.** Basic-256mb names the RAM, not the disk. The
   Archive grows monotonically (transcript segments are JSON blobs in
   `transcript_versions.segments`). Get the current DB size and the plan's
   storage ceiling, and record both. A full disk on Postgres is a hard
   outage, and this is the first resource here that grows without anyone
   deciding it should.
2. **What the recovery window actually is.** Per Render's docs, PITR exists
   on paid instances but the window follows the *workspace* tier — 3 days
   on Hobby, 7 on Pro — and upgrading doesn't backfill it. Confirm which
   applies. Three days is short for a solo operator: a bad migration on a
   Friday, noticed the next Wednesday, is past the window.
3. **Write down the restore procedure.** Render's PITR spins up a *new*
   instance rather than rewinding the existing one, so recovery is a
   swap — reconnect three services to a new `DATABASE_URL` under pressure.
   That's not a button. Document the steps in `README.md`, and do one
   throwaway PITR restore to a scratch instance to confirm the procedure is
   real. An untested restore isn't a backup.

**Acceptance.** `render.yaml` describes every paid resource. A deliberate
hostname mismatch in local env produces a clear startup error. Storage
headroom, PITR window, and a tested restore procedure are all written down.

**Status.** Startup hostname assertion shipped and merged (WO-4 part 1,
`archive/db/engine.py`'s `_assert_expected_db_host()`, gated on a new
`EXPECTED_DB_HOST` env var so it can never crash a staging/test deploy
that doesn't set it). Cost inventory recorded in
`rtr-business/BUSINESS_OVERVIEW.md` with real, confirmed figures. Storage
headroom confirmed (25.17% of 1GB used, 2026-08-17). PITR window confirmed
(**Hobby tier, 3 days**) and the restore procedure written up in
`README.md`'s new "Backups and recovery" section.

**`databases:` block merged 2026-08-17 (PR #107), and verified clean
against the live Render dashboard** — Ryan confirmed all four checks
post-sync: (1) the Blueprint sync event completed successfully, (2) no
duplicate `rtr-deeplink-db` instance was created, (3) the adopted
instance's plan/RAM/storage/hostname are all unchanged from before the
sync, (4) both `rtr-deeplink-archive` and `rtr-transcription-worker`
booted cleanly afterward (proving `EXPECTED_DB_HOST` matched for real, not
just in local tests). First time this repo has adopted an existing
database (not a compute service) into a Blueprint, and it went cleanly.

**One real item still open, not silently dropped: the actual PITR test
restore.** The README procedure (`README.md`'s "Backups and recovery")
is written from Render's documented behavior plus this workspace's
confirmed real settings, but nobody has clicked through an actual
recovery yet — a cross-checked hypothesis, not a proven procedure. Needs
Ryan to do one throwaway restore to a scratch instance (never repointing
any real service at it). Tracked as its own live entry in `BACKLOG.md`.

---

## Wave 5 — migrations survive deploys ("a quiet day")

**Blocked on Ryan's prod `DATABASE_URL` access.** The single most
incident-prone area of this repo (three documented incidents). Schedule
last, do not parallelize other DB-schema-touching work against it.
~1 day.

### WO-10 · Make migrations survive deploys — **~1 day, do carefully** · *blocked on P1*

**Problem.** Code deploys automatically; the matching `ALTER TABLE` waits
for a human, and the gap is unbounded. `create_all()` runs unconditionally
at startup (`app/db/engine.py:36-40`, `archive/db/engine.py:39-57`), which
masks any add-a-table migration so `alembic_version` silently falls behind.
Three documented incidents: 2026-08-09, 08-10, 08-13
(`archive/alembic/README.md:198-291`).

**This contradicts a documented convention on purpose.** `CLAUDE.md`
currently presents `create_all()` as the deliberate zero-friction path for
new tables. That guidance is what makes the drift invisible. Updating
`CLAUDE.md` is part of this work order, not an afterthought.

**Strict order — do not reorder:**

1. Gate `create_all()` to SQLite/dev only. Verify no fresh-table path in
   prod depends on it. **Land and deploy this alone.**
2. One-time reconciliation: run `alembic current` against **both** prod
   services, compare against `head`, and stamp/upgrade until they genuinely
   agree. Use `/internal/schema-info` to confirm real reflected columns
   rather than trusting `alembic_version`. Requires prod `DATABASE_URL` —
   Ryan's involvement. `app/alembic/README.md:53-56` says the resolver's
   history has never been stamped in prod; confirm whether that's still true.
2. Only then add a `preDeployCommand` running `alembic upgrade head` per web
   service, so schema lands before code.

**Acceptance.** A test migration adding a column deploys cleanly with no
manual step. `alembic current` equals `head` on both services. Automating
step 3 before step 2 will fail on the first run — the drift is already there.

---

## Wave 6 — recurring bug-class cleanup · **COMPLETE 2026-08-16**

No blockers, lower urgency than Waves 1-5 — fill gaps between waves or run
after. ~2-3 days. Three items pulled from `BACKLOG.md`'s Bugs section and
Archive-roadmap-adjacent findings, chosen because each fixes a *pattern*
behind several already-open bugs rather than one instance.

### WO-14 · Shared bounded-extraction jurisdiction-regex helper — **new** — **DONE 2026-08-16**

**Problem.** `GranicusAssetFinder._extract_metadata()`'s jurisdiction regex
has no sentence/tag boundary and swallows unrelated agenda text into the
stored jurisdiction — confirmed live on 9 real Granicus customers (Sarasota,
Punta Gorda, Huntsville, Fort Worth, Edgewater, Castle Rock, Castle Pines,
Boston, Milwaukee). The **identical bug exists independently** in
`escribe.py` (not shared code), confirmed on 6 real examples including 4
Canadian cities. A naive port of PrimeGov's existing fix won't work here —
some bleed examples are themselves ALL-CAPS agenda headings.

**Do.** Design one shared bounded-extraction helper both adapters can call,
rather than patching each site independently — the two confirmed instances
of the same bug class are the signal that a shared fix is worth it over two
one-offs.

**Acceptance.** Existing fixture tests for both adapters still pass. New
regression tests cover at least the 9 Granicus and 6 eScribe confirmed-bleed
examples above.

**Fixed.** Both Granicus and eScribe now call the already-built
`jurisdiction_enrich.extract_jurisdiction_chain()` (it existed from prior
work but was never wired into these two adapters). Also fixed eScribe's
subdomain fallback, which was mangling multi-word Canadian city names
("Thunderbay" instead of "Thunder Bay"). Live re-verified against
`hercules.granicus.com/player/clip/1306`. Full detail, all 9 Granicus + 6
eScribe cases, and one honestly-flagged residual gap (4 Granicus cases
that only resolve via subdomain-fallback luck, not the text-chain itself)
in `BACKLOG_DONE.md` / `BACKLOG.md`.

### WO-15 · Stale-archived-page refresh path — **new** — **DONE 2026-08-16**

**Problem.** Two confirmed gaps combine into one recurring root cause:
re-submitting an already-archived URL through the public API never
triggers a refresh (it short-circuits to the cached lookup; only a
token-gated admin endpoint or the passive 30-day recheck cycle re-resolves
it), and the YouTube transcript-wanted queue only ever surfaces pages with
**no** transcript, never an existing-but-bad one. `BACKLOG.md` traces this
exact pattern as the likely root cause behind several separately-filed
"why does this page look wrong" bugs: `riversidecountyca.iqm2.com`
title/jurisdiction, several OCFL/Sacramento/Maricopa pages, and the
Fountain Valley clip 607 title/jurisdiction mismatch.

**Do.** Build a real re-resolve/refresh mechanism reachable without the
admin token — e.g. a rate-limited "refresh this page" path — and extend the
YouTube transcript-wanted queue to also surface existing-but-flagged-bad
transcripts, not just missing ones.

**Acceptance.** Re-submitting a known-stale archived URL produces updated
content without needing the admin token. At least one of the BACKLOG.md
bugs this WO is meant to explain (Fountain Valley clip 607 is the most
concrete) is re-verified and closed as a consequence, not just theorized.

**Fixed.** New public, rate-limited `POST /api/refresh-archived-page`
(app/main.py) + a "Refresh this page" button on the Archive's meeting
page, reusing the existing `_recheck_archived_page()` resolve/push logic
so no new resolve code was written. `list_youtube_pages_missing_
transcripts()` now reuses the same quality gate `_has_good_transcript()`
already provides, so an existing-but-garbled default resurfaces in the
queue too — which surfaced a second real gap (a fresh push there wouldn't
auto-promote over an already-has-segments+language default), fixed by
having `fetch_youtube_transcripts.py` always call the already-built
promote endpoint after a push. Live-verified end-to-end in a local
resolver+Archive pair (cooldown, then a real recheck past cooldown).
**Not verified against a real already-broken production page** (Fountain
Valley clip 607, `riversidecountyca.iqm2.com`) — both of those pages'
underlying adapter bugs are still separately unfixed, so there's nothing
for this mechanism to have fixed yet; re-verifying live once either
adapter bug lands is a natural follow-up, not done here. Full detail in
`BACKLOG_DONE.md`.

### WO-16 · Census-table jurisdiction gaps — **new** — **DONE 2026-08-16**

**Fixed (part 1, the one real code change).** Townships/county
subdivisions (Upper Providence PA, Greenburgh NY, Upper Dublin PA) were
missing from the Census-table lookup entirely -- Census tracks them as a
separate gazetteer. (Full context on the other two parts of this WO is in
the Problem/Do/Acceptance below, kept in the original order.)

**Problem.** The 2026-08-14 649-jurisdiction Census-table validation audit
left four categories of confirmed gaps: two archived pages store a literal
date as their jurisdiction (source untraced); townships/county subdivisions
are missing from the lookup table entirely (Upper Providence PA, Greenburgh
NY, Upper Dublin PA — confirmed real, not fabricated); and Elliot Lake, ON
needs a country-exemption flag since it's Canadian and was never going to
be in a US Census table.

**Do.** Trace the two date-as-jurisdiction pages to their root cause before
fixing (don't paper over with a filter). Add the confirmed township/county
subdivisions to the lookup table. Add a country field or exemption flag so
non-US jurisdictions like Elliot Lake stop being treated as lookup misses.

**Acceptance.** All four confirmed cases resolve correctly on re-check. The
fix doesn't silently swallow future genuine lookup misses — a real miss
should still be visibly flagged, not defaulted away.

**Fixed (part 1, the one real code change).** New
`build_county_subdivisions()` + `county_subdivisions.csv`, wired into
`jurisdiction_enrich.py`'s `_table_lookup()` as a third tier. Surfaced a
real, narrow finding along the way: "Oshawa" (Ontario) also happens to be
a real, obscure Minnesota township — traced end-to-end and confirmed
harmless (stored jurisdiction text is unaffected, only an invisible
internal confidence tag changes).

**Investigated, no code change needed (parts 2 and 3).** The two
literal-date-as-jurisdiction pages are no longer reproducible on
production (a fresh live scan of all 843 `/coverage` rows found zero
date-shaped jurisdictions) — likely already closed by WO-14 or parallel
work, not independently root-caused here. Elliot Lake, ON: directly
tested and confirmed today's code already handles it correctly
(`"unverified"`, the documented-correct category for untabled entity
types) — no live bug, no fix needed. Full detail, including why each
"no fix needed" conclusion was reached rather than assumed, in
`BACKLOG_DONE.md`.

---

## Not in scope for the dev team

- **Privacy policy and terms.** No template or route exists, while the site
  runs GA, collects emails, and stores `clerk_user_id`. This is Ryan's to
  draft with a lawyer, not a dev ticket. Tracked in `rtr-business/TASKS.md`.
- **The trust & safety threat model** (`BACKLOG.md`, 2026-08-10). Still
  unbuilt, deliberately out of this brief — it's a product decision about
  what to do with spoofed content, not a hygiene fix.
- **Accessibility tooling.** `aria-` usage holds up on inspection; adding
  Lighthouse CI or axe is worth doing eventually but shouldn't displace
  anything above it.

---

## Docs debt to clear alongside

Two confirmed contradictions, both about saved-search alerts, which shipped
2026-08-13 as PR #30 and run daily via `send-search-alerts.yml`:

- `README.md:753-756` — "**Not yet built**: saved-search alert emails" —
  **fixed** (re-checked 2026-08-16, this repo's README no longer says it).
- `rtr-business/BUSINESS_OVERVIEW.md:86` — "Not built yet: billing of any
  kind, saved-search alert emails, …" — **still stale as of 2026-08-16**,
  confirmed by direct grep. This lives in the separate `rtr-business`
  workspace, so it's not one of the WOs above, but worth a one-line fix
  next time anyone is in that repo — it's exactly the kind of drift the
  rule below exists to prevent.

Then add the rule to `CLAUDE.md`: **a PR that ships a feature must
update every doc that named it as unbuilt, and the PR description must list
which.** The audit found three of eight of its own starting leads were wrong
because they were written from these docs — the docs here are good enough
that people, and agents, treat them as ground truth. That's exactly why the
drift is expensive.
