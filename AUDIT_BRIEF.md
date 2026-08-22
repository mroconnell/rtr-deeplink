# App-wide audit: industry best practices & resource management

Scoped 2026-08-14, written for handoff. Each area below is a real,
open thread with what has actually been checked so far — not a
generic checklist. Two areas closed 2026-08-21 and are kept here
rather than deleted, so a later pass can see what was already
settled and why.

The execution half of the original audit lives in
`AUDIT_EXECUTION_BRIEF.md` and `BACKLOG_DONE.md`; the
confirmations nobody has watched happen yet are in `BACKLOG.md`
under **Needs a human**.

Split out of [BACKLOG.md](BACKLOG.md) 2026-08-22; that file keeps a
short stub entry pointing here. Update both together.

---

The tool itself works well now — 15+ platform adapters, 683 tests,
accounts, on-demand transcription, admin outcome reporting. This section
scopes a **broad audit of everything around the tool**: heavy investment
in features/reliability, comparatively little in discoverability, user
validation, and standard engineering/business hygiene. Intended to be
**handed to a separate agent (Cowork)** — written self-contained (real
file paths, real findings, real open questions).

**Starting leads, not finished verification:**

- **[IMPROVEMENT-ROUND] User feedback & validation — the single biggest
  blind spot found.** Only feedback channel is a passive mailto link,
  never surfaced mid-use. `ProblemReport` is scoped narrowly to
  content-quality bugs, not general product feedback. GA's `trackEvent()`
  is wired but was, at last check, only fired from three call sites
  total — no event for a successful resolve, a save, or a returning
  visitor (though see the GA confirmation entry under **Needs a human**,
  which closed part of this gap 2026-08-17). No documented user
  interview/usability session exists for *this* product — the "two
  things people wanted" finding `CLAUDE.md` cites is from round 1's
  different, superseded product. Matters most right now because the
  first-10 outreach and clips campaign are starting — the cheapest
  window there will ever be to instrument real signal.
- **[IMPROVEMENT-ROUND] Discoverability — already the subject of its own
  backlog work** (`CLAUDE_BACKLOG.md`'s "Discoverability additions",
  `rtr-business/marketing/discoverability-ideas.md`) — included only as
  a pointer so the audit doesn't duplicate it.
- **[JUST-DO-IT] Docs hygiene — a live, confirmed example of drift.**
  Saved-search alert emails (a real daily cron, merged 2026-08-13) are
  described as unbuilt future work in `rtr-business/BUSINESS_OVERVIEW.md`'s
  "Not built yet" list — still wrong, not this repo so out of scope for
  a code-repo pass. Worth checking whether other recently-merged work has
  the same gap.
- **[NEEDS-AUDIT] Legal/compliance — already tracked in
  `rtr-business/TASKS.md`**, included only as a cross-reference: no
  privacy policy/ToS live, LLC formation status TBD, the Clerk
  `user.deleted` → data-purge cascade has unit coverage but has never
  fired against a real account (see **Needs a human**).
- **[Closed 2026-08-21] Data durability** — a real Postgres PITR test
  restore was performed and verified against real data 2026-08-17.
- **[Closed 2026-08-21] Security scanning** —
  `.github/dependabot.yml` exists and `pip-audit` runs on every PR
  (WO-11). The *other* half of the original bullet — the self-authored
  fake/spoofed-content threat model having few built mitigations — is
  real, partly addressed, tracked under **Trust, safety & data quality**.
- **[NEEDS-AUDIT] Financial/resource management — costs not fully
  inventoried.** `rtr-business/TASKS.md` already flags this: the
  transcription worker's $25/mo is the only confirmed recurring cost;
  web plans, domain, Resend, Clerk have no confirmed monthly total. No
  pricing decided, no revenue. Worth pairing with a real Render
  usage/cost review.
- **[NEEDS-AUDIT] Accessibility — a positive finding on a shallow
  check.** `aria-` attributes and `lang` appear across most templates —
  better than expected on a five-minute grep. No automated a11y check
  (Lighthouse CI, axe) exists to keep it that way as the site grows.

**Scoping notes for whoever picks this up**: every finding above is a
starting lead, not a finished conclusion — verify before acting on any of
them. Deliberately broad (reliability, security, compliance, cost,
process, user/product validation) rather than scoped to one fix — this
list is a floor, not a ceiling.
