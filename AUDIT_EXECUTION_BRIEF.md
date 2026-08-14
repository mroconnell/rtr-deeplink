# Audit execution brief — rtr-deeplink

**Source:** `AUDIT_2026-08-14.md` (in this repo root and in `rtr-business/`)
**For:** Claude Code sessions working against `rtr-deeplink`
**Written:** 2026-08-14, against commit `bf3ef7f`

Twelve work orders, in dependency order. Each is sized to one PR. Pick one,
do it completely, land it, move on — do **not** batch several into one
branch. Several of these touch deploy-time behaviour, and a mixed PR makes
a bad deploy impossible to bisect.

---

## Before you touch anything

Four hazards specific to this repo. All are documented in `CLAUDE.md`; they
are repeated here because every work order below is affected by at least one.

1. **A merge to `main` deploys to production immediately.** `render.yaml`
   Blueprint sync fires on every push. There is currently no test gate
   (that's WO-3). Until WO-3 lands, treat every merge as a production
   deploy you are personally responsible for verifying.
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
| P1 | ~~Render → both Postgres instances: what plan?~~ **ANSWERED 2026-08-14:** `rtr-deeplink-db` is **Basic-256mb** (paid, ~$6/mo) — not at risk. Staging is free and expires 9/9/2026, which is intentional and disposable. Remaining sub-questions folded into WO-4 below. | WO-4, WO-10 |
| P2 | Render → all three services: does the live plan match `render.yaml` (`starter`, `starter`, `standard`)? Current month's actual bill? | WO-4 |
| P3 | GA: is the property receiving events? Are `submit_meeting_url` and `copy_link_to_time` visible in the last 30 days? | WO-9 |
| P4 | Resend + Clerk: plan, cost, distance from free-tier ceiling. | WO-4 |
| P5 | Actions → a recent `send-search-alerts` run: did a real alert email actually send? | — (informational) |

**P1 is the highest-consequence unknown in the audit.** Do it first.

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

## Phase 2 — the week after

**Start with WO-5, not WO-4.** WO-4 is blocked on external checks P1, P2,
and P4; WO-5 is blocked on nothing. Numbering here is dependency order
within the audit, not a queue.

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

### WO-5 · SSRF guard on the resolve entrypoint — **2-4 hrs**

**Problem.** `ResolveRequest.url` is a bare `str` (`app/main.py:113-114`).
Unknown hosts fall through to the generic fallback, which does
`session.get(url, allow_redirects=True, ...)`
(`app/platforms/generic_fallback.py:481-483`) with no scheme allowlist, no
private-IP rejection, no per-hop redirect validation, and no response-size
cap. `GENERIC_FALLBACK_HEADLESS=1` is on in production, so a real browser
loads whatever it's pointed at. An anonymous POST of
`http://169.254.169.254/...` or an internal Render hostname is fetched from
inside the network, and content can return in the resolve payload.

**Do.** One shared helper — `app/utils/url_guard.py` — applied at the
entrypoint so every adapter inherits it:

- scheme in `{http, https}` only;
- resolve the hostname, reject loopback / private / link-local / multicast /
  reserved ranges;
- cap redirects and re-run the check on **each hop** (a permitted host can
  302 to a private one);
- cap response body size.

Wire it into the resolve path and the generic fallback's own fetches. It
must also guard the headless escalation.

**Acceptance.** Tests for each rejected class, including the redirect-to-
private-IP case, which is the one people forget. A rejected URL returns a
clean user-facing error, not a stack trace. Existing adapter tests still
pass — if a fixture host trips the guard, that's a real finding, not a
reason to loosen it.

### WO-6 · Health checks that can fail — **1-2 hrs**

**Problem.** `render.yaml:47,128` gate deploys on `/api/health`, and both
handlers return a static `{"status": "ok"}` (`app/main.py:268-270`,
`archive/main.py:109-111`). During the 2026-08-09 incident the app was
failing every query on a missing column and would still have reported `ok`.

**Do.** Execute `SELECT 1` (and on the Archive, a cheap count against one
real table). Return 503 with a short reason on failure. Keep it cheap —
Render polls this frequently.

**Acceptance.** With the DB unreachable locally, the endpoint returns 503.
After deploy, confirm in Render that the health check gate actually fails a
deploy when the endpoint is unhealthy — an unverified gate is the same
problem in a new costume.

### WO-7 · Know when production breaks — **2-3 hrs**

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

**Acceptance.** A deliberately raised exception on a staging path appears in
Sentry. A forced metric failure turns the daily-report workflow red.

### WO-8 · Admin token out of the URL — **~45 min**

**Problem.** `daily-report.yml:38` and `send-search-alerts.yml:37` both send
`?token=${{ secrets.ADMIN_STATS_TOKEN }}`. GitHub masks it in Actions logs;
Render's request logs do not. The Archive already does this correctly at
`archive/main.py:100-106`.

**Do.** Accept `Authorization: Bearer` on the admin routes in `app/main.py`,
keeping query-param support temporarily so the switch isn't a flag day.
Update both workflows to `curl -H`. Then remove the query-param path in a
follow-up once you've confirmed both crons ran green.

**Acceptance.** Both workflows pass with header auth. `secrets.compare_digest`
still used (don't regress to `==`).

### WO-9 · The three events that make outreach measurable — **~1 afternoon** · *blocked on P3*

**Problem.** Five GA events exist (`submit_meeting_url` at
`app/templates/index.html:26`, three `copy_link_to_time` in `player.js`, one
`newsletter_signup`). Missing: whether a resolve **succeeded**, whether
anyone **played** the video, and any way to attribute a visit to an outreach
recipient.

**Do.** Fire `resolve_result` with `{status, platform}` from the resolve
response handler; `video_play` and `transcript_seek` from `player.js`, which
already has `trackEvent` in scope. Keep params low-cardinality — no URLs, no
anything user-identifying.

**Ryan's half, and it needs no code:** every personalized link in the
first-10 campaign gets
`?utm_source=outreach&utm_campaign=first10&utm_content=<recipient-slug>`.
GA segments on that automatically. **This is unrecoverable if the first
emails go out without it** — settle the convention before WO-9 is even
written.

**Acceptance.** All three events visible in GA realtime during a manual
walkthrough. Confirm the UTM parameters survive the `/meeting` →
`/m/{slug}` archive redirect; if they don't, that's a real bug and the
campaign's attribution depends on fixing it.

---

## Phase 3 — a quiet day

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

### WO-11 · Pin dependencies, then scan them — **2-3 hrs**

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

**Acceptance.** One verification deploy per service off the lockfile.
Dependabot opens PRs. `yt-dlp` still floats.

### WO-12 · Linter and formatter — **1 hr config, 2-4 hrs first pass**

**Problem.** No ruff/black/mypy/pre-commit config anywhere. Given that
multiple sessions edit this tree the same day, a formatter is mostly about
keeping `git pull --rebase` clean — gratuitous whitespace diffs are what
turn a clean rebase into a conflicted one.

**Do.** Add `ruff` (lint + format in one tool) to `requirements-dev.txt`, a
minimal config block, and a `ruff check` / `ruff format --check` step in the
WO-2 workflow. Land the bulk reformat as its **own** commit so it doesn't
poison `git blame` on the config commit.

**Skip mypy.** Retrofitting types here is a multi-day project with unclear
payoff at this stage.

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

- `README.md:753-756` — "**Not yet built**: saved-search alert emails"
- `rtr-business/BUSINESS_OVERVIEW.md:86` — "Not built yet: billing of any
  kind, saved-search alert emails, …"

Fix both. Then add the rule to `CLAUDE.md`: **a PR that ships a feature must
update every doc that named it as unbuilt, and the PR description must list
which.** The audit found three of eight of its own starting leads were wrong
because they were written from these docs — the docs here are good enough
that people, and agents, treat them as ground truth. That's exactly why the
drift is expensive.
