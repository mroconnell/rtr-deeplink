# Audit execution brief — rtr-deeplink

**Source:** `AUDIT_2026-08-14.md` (in this repo root and in `rtr-business/`)
**For:** Claude Code sessions working against `rtr-deeplink`
**Written:** 2026-08-14, against commit `bf3ef7f`
**Re-sequenced 2026-08-16:** Phase 2/3 re-grouped into six waves after a
roadmap-planning pass (reliability/ops lens, ~2-4 week horizon).
**Trimmed 2026-08-17:** Phase 1 and Waves 1, 2, 3, 4, and 6 (WO-1 through
WO-9, WO-11 through WO-16 — everything except WO-10) are all complete and
verified. Their full Problem/Do/Fixed detail moved to `BACKLOG_DONE.md`'s
"Reliability/ops audit execution" entry, so this file stays focused on
the one thing still actually open rather than re-reading six waves of
history to find it. A handful of small Ryan-owned dashboard/manual checks
those waves left open (Sentry exception verification, confirming the
Render health-check gate blocks a bad deploy, confirming both admin crons
run green before removing WO-8's query-param fallback, confirming a real
Render deploy off the new pinned lockfiles, GA event visibility, a real
sent alert email, one un-landed doc-hygiene rule) are consolidated into
one live checklist in `BACKLOG.md`: "Reliability/ops audit — remaining
manual/dashboard checks" — not repeated here.

**Wave 5 (WO-10) landed 2026-08-17 for the Archive service** — the one
that has actually had schema incidents. `archive/db/engine.py`'s
`create_all()` is a no-op on Postgres; `render.yaml`'s
`rtr-deeplink-archive` runs `preDeployCommand: cd archive && alembic
upgrade head` before each build goes live; CI runs `alembic check`
(models vs. a fresh migration-built SQLite) on every PR. Steps 1–3
below were done in one PR because step 2's precondition was already
met that day (Ryan ran `alembic upgrade head` on the archive twice, so
`alembic_version` == head == `c1d2e3f4a5b6`, and `alembic check` on a
fresh `upgrade head` DB showed no missing model tables/columns). **What
remains of WO-10 is the resolver half, and it is Ryan-gated**. Its
*code* landed 2026-08-21 (WO-24): `app/db/engine.py`'s `create_all()`
is a no-op on Postgres, CI runs a second `alembic check` with
`working-directory: app`, and `GET /admin/schema-info` on the resolver
(a port of the Archive's `/internal/schema-info`) reports its real
reflected columns and `alembic_version` without shell access. What's
left is the one human step: the resolver's Alembic history
(`app/alembic/`, 2 revisions) has never been stamped in prod, so its
`preDeployCommand` would fail on first run (exactly the "step 3 before
step 2" warning below). **The runbook is `app/alembic/README.md`'s "The
runbook" section — it branches, so don't shortcut it.** Two corrections
to what this file used to say: stamp the literal revision
`a9207c0eb761`, **never** the word `head` (head moved on 2026-08-15,
and stamping it would claim production has `jurisdiction_confidence`
whether or not it does — the 2026-08-09 archive incident's exact
shape), and don't "expect empty" from `alembic current` (a 2026-08-11
`information_schema` query found an `alembic_version` table already
present there). Start by curling `/admin/schema-info`: if
`jurisdiction_confidence` is missing from `meeting_resolutions`, that's
a live silent-degradation bug, not just a migration chore — see
`BACKLOG.md`'s entry for why. Then the `render.yaml`
`preDeployCommand` (already written, held back deliberately) can merge.
Tracked in `BACKLOG.md`'s "Schema-migration deploy ordering" entry.
Full detail: `BACKLOG_DONE.md`'s "WO-10" entry. The original work-order
text is kept below for the resolver follow-up.

---

## Before you touch anything

Four hazards specific to this repo, all documented in `CLAUDE.md`, all
relevant to WO-10 specifically since it's the most schema/deploy-sensitive
work order in the whole plan.

1. **A merge to `main` deploys to production immediately.** `render.yaml`
   Blueprint sync fires on every push. CI branch protection blocks a
   failing test, not a passing test with a bad live consequence. Treat
   every merge as a production deploy you are personally responsible for
   verifying.
2. **This clone may be shared with another active session.** Run `git
   status` first. If there are uncommitted changes that aren't yours,
   don't touch them — isolate your work with `git worktree add
   /tmp/<name> origin/main`, then `gh pr create` + `gh pr merge --squash
   --delete-branch` from the worktree. Do not push a differently-named
   branch onto `main` via refspec; it gets flagged.

   **Hard rule:** never run `git reset --hard`, `git checkout .`, or
   `git clean -fd` without running `git stash -u` immediately before it
   — not "unless you checked earlier," the check can go stale between
   then and the destructive command.
3. **Never grep a gitignored file with a broad pattern.** A real incident
   echoed a token's plaintext value into a transcript and forced a
   rotation in three places. If you need an env var's value, ask Ryan.
4. **Schema changes are not automatic.** *(Largely fixed — this is the
   pre-WO-10 state, kept because the resolver's last step is still
   open.)* `create_all()` no longer runs on Postgres in **either**
   service as of 2026-08-21, so every prod schema change needs an
   Alembic migration. The Archive applies them automatically on deploy
   (`preDeployCommand`); the resolver still needs a hand-run migration
   for an altered table until its one-time stamp happens. Read WO-10
   below fully before starting, the order matters.

**Definition of done:**

- `pytest` passes locally, and `npm test` if you touched JS.
- Any doc that made a claim your change invalidates is updated **in the
  same PR** — `README.md`, `CLAUDE.md`, `BACKLOG.md`, and
  `../rtr-business/BUSINESS_OVERVIEW.md` are all in scope. The PR
  description lists which docs you touched and why.
- The corresponding `BACKLOG.md` entry moves to `BACKLOG_DONE.md` with
  the investigation detail, per existing convention.
- If the change affects production behaviour, the PR description says
  how you verified it live, or says explicitly that you couldn't.

---

## Prerequisites

All dashboard checks that ever blocked code work are answered — P1
(`rtr-deeplink-db` is Basic-256mb, confirmed) is the one WO-10 itself
depends on. P3 (GA event visibility) and P5 (a real sent alert email) are
informational only at this point and tracked in `BACKLOG.md`'s
consolidated checklist rather than here, since neither blocks WO-10.

---

## Wave 5 — migrations survive deploys ("a quiet day")

**Blocked on Ryan's prod `DATABASE_URL` access.** The single most
incident-prone area of this repo (three documented incidents). Schedule
last, do not parallelize other DB-schema-touching work against it.
~1 day.

### WO-10 · Make migrations survive deploys — **~1 day, do carefully** · *blocked on P1 (answered)*

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

**Strict order — do not reorder:** *(step 1 is done for both services;
step 2 is done for the archive and is the resolver's remaining gate.)*

1. ~~Gate `create_all()` to SQLite/dev only. Verify no fresh-table path in
   prod depends on it. **Land and deploy this alone.**~~ Done — archive
   2026-08-17, resolver 2026-08-21.
2. One-time reconciliation: run `alembic current` against **both** prod
   services, compare against the specific revision the real schema
   matches, and stamp/upgrade until they genuinely agree. Confirm real
   reflected columns rather than trusting `alembic_version` — the
   archive's `/internal/schema-info`, and now the resolver's own
   `/admin/schema-info`. Requires prod shell/`DATABASE_URL` access —
   Ryan's involvement. **Done for the archive; still open for the
   resolver**, whose branching runbook is in `app/alembic/README.md`.
   Note the stamp target is the literal `a9207c0eb761`, not `head`.
3. Only then add a `preDeployCommand` running `alembic upgrade head` per web
   service, so schema lands before code. Done for the archive; written
   but deliberately held for the resolver until step 2 lands.

**Acceptance.** A test migration adding a column deploys cleanly with no
manual step. `alembic current` equals `head` on both services. Automating
step 3 before step 2 will fail on the first run — the drift is already there.

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
